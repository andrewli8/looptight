"""CLI smoke tests — the commands wire up and exit cleanly."""

from __future__ import annotations

import argparse
import json
import subprocess

import pytest

from looptight.cli import build_parser, main
from looptight.commands import _is_python_verify
from looptight.protocol_commands import _verify_exit_code
from looptight.propose import propose


def test_is_python_verify_recognises_all_python_runners():
    # All three branches (pytest / py.test / python -m) must match; a rename or
    # typo in commands.py:61-63 would otherwise go undetected.
    assert _is_python_verify("pytest -q")
    assert _is_python_verify("py.test --tb=short")
    assert _is_python_verify("python -m unittest discover")
    assert not _is_python_verify("cargo test")
    assert not _is_python_verify("go test ./...")


def test_run_parser_accepts_resume_on_limit_flags():
    args = build_parser().parse_args(
        ["run", "--headless", "g", "--resume-on-limit", "--limit-backoff-seconds", "15"]
    )
    assert args.resume_on_limit is True
    assert args.limit_backoff_seconds == 15.0
    assert args.limit_max_wait_seconds == 3600.0


def _commit_fixture():
    # Commit fixture files so the worktree is clean when `next` runs (next refuses a
    # dirty worktree). Mirrors the real loop: code is committed before claiming a task.
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "fixture", "--allow-empty"],
        check=True,
    )


def _reset_claims():
    # Drop the coordinator's claim store so a following `next` re-offers the task. In a real
    # repo a claim persists, so re-running `next` will not re-hand a claimed task; these tests
    # assert determinism ("same committed code -> same decision"), which a fresh session sees.
    from pathlib import Path as _Path

    from looptight.coordinator import coordinator_path

    path = coordinator_path(_Path.cwd())
    if path is not None and path.exists():
        path.unlink()


def test_init_writes_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert main(["init"]) == 0
    text = (tmp_path / ".looptight.toml").read_text()
    assert 'verify = "pytest -q"' in text


def test_init_creates_gitignore_for_pycache_on_python_loop(tmp_path, monkeypatch, capsys):
    # A pytest verify leaves untracked __pycache__/; without a .gitignore the first
    # `next` after `verify` refuses the dirty worktree and stalls the shipped loop. init
    # must create a one-line .gitignore so the out-of-box Python loop runs.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    assert main(["init"]) == 0
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists(), "init did not create a .gitignore for the Python loop"
    assert "__pycache__/" in gitignore.read_text()
    assert "__pycache__" in capsys.readouterr().out  # init reports the write


def test_init_never_rewrites_an_existing_gitignore(tmp_path, monkeypatch):
    # init owns only files it creates: an existing user .gitignore stays byte-for-byte,
    # even if it does not mention __pycache__.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    original = "node_modules/\n"
    (tmp_path / ".gitignore").write_text(original)

    assert main(["init"]) == 0
    assert (tmp_path / ".gitignore").read_text() == original


def test_init_guides_committing_the_config_before_next(tmp_path, monkeypatch, capsys):
    # init writes an untracked .looptight.toml; the documented next step `next`
    # refuses a dirty worktree, so a first-run user who runs init then next hits a
    # dead-end caused by init's own output. init must guide them to commit it.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert main(["init"]) == 0
    out = capsys.readouterr().out.lower()
    assert "commit" in out, "init does not tell the user to commit the new config"
    assert ".looptight.toml" in out


def test_init_message_is_consistent_when_verify_undetected(tmp_path, monkeypatch, capsys):
    # render_config writes a `pytest -q` default even when nothing is detected, so
    # the message must not contradict it ("set verify" as if unset while the file
    # already has pytest -q). It should name the default it wrote and say replace.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_verify", lambda *a, **k: None)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)

    assert main(["init"]) == 0

    out = capsys.readouterr().out
    text = (tmp_path / ".looptight.toml").read_text()
    assert 'verify = "pytest -q"' in text  # render_config's default
    assert "pytest -q" in out  # the message names what it actually wrote
    assert "replace" in out.lower()  # and guides the user to replace it
    assert "set `verify` in the config" not in out  # no longer claims it is unset


def test_init_credits_explicit_flags_not_detection(tmp_path, monkeypatch, capsys):
    # When the user passes --verify/--agent, init must not claim it "detected" a
    # value the user typed; it should say the value came from the flag.
    monkeypatch.chdir(tmp_path)

    assert main(["init", "--verify", "make test", "--agent", "codex"]) == 0
    out = capsys.readouterr().out
    assert "from --verify" in out and "Detected:" not in out
    assert "from --agent" in out and "auto-detected" not in out


def test_init_does_not_clobber_existing_config(tmp_path, monkeypatch, capsys):
    # Re-running init must not silently destroy a user's customized config.
    monkeypatch.chdir(tmp_path)
    existing = '# custom\nverify = "make check"\nbudget_usd = 5.0\n'
    (tmp_path / ".looptight.toml").write_text(existing)
    assert main(["init"]) == 0
    assert (tmp_path / ".looptight.toml").read_text() == existing  # untouched
    assert "exist" in capsys.readouterr().out.lower()


def test_init_integrates_even_when_config_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')

    assert main(["init", "--integrate"]) == 0

    assert "looptight next --json" in (tmp_path / "AGENTS.md").read_text()
    assert "looptight next --json" in (tmp_path / "CLAUDE.md").read_text()


def test_bare_goal_refuses_implicit_child_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)
    # No agent on PATH → clean exit code 2, not a crash.
    assert main(["fix the failing tests"]) == 2


def test_run_requires_explicit_headless(capsys):
    assert main(["run", "goal"]) == 2
    assert "--headless" in capsys.readouterr().out


def test_headless_run_refuses_git_primary_worktree_before_provider(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda *args: pytest.fail("provider adapter must not be loaded"),
    )

    assert main(["run", "--headless", "fix it", "--agent", "codex", "--verify", "true"]) == 2
    assert "primary worktree" in capsys.readouterr().out.lower()


def test_headless_run_allows_primary_worktree_with_direct_main(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text("direct_main = true\n")
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda *args: adapter)

    assert main(["run", "--headless", "fix it", "--agent", "codex", "--verify", "true"]) == 0
    assert adapter.iterations_run == 1


def test_headless_run_allows_isolated_git_worktree(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    isolated = tmp_path / "isolated"
    primary.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=primary, check=True)
    (primary / "tracked").write_text("content\n")
    subprocess.run(["git", "add", "tracked"], cwd=primary, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=primary, check=True)
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(isolated)], cwd=primary, check=True)
    monkeypatch.chdir(isolated)
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda *args: adapter)

    assert main(["run", "--headless", "fix it", "--agent", "codex", "--verify", "true"]) == 0
    assert adapter.iterations_run == 1


def test_improve_is_deprecated_without_launching_agent(capsys):
    assert main(["improve", "--headless"]) == 2
    out = capsys.readouterr().out.lower()
    assert "deprecated" in out
    assert "next" in out


def test_improve_with_a_goal_still_shows_deprecation_guidance(capsys):
    # The old `improve` took a goal, so `improve "<goal>"` (muscle memory) must reach the migration
    # guidance, not error with a bare argparse usage that hides how to migrate.
    assert main(["improve", "build a thing"]) == 2
    out = capsys.readouterr().out.lower()
    assert "deprecated" in out and "init --integrate" in out


def test_run_exits_error_when_no_verify_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter())
    # No config, no verify markers → no verify command → exit 2.
    assert main(["run", "--headless", "fix tests"]) == 2


def test_main_handles_keyboard_interrupt_cleanly(monkeypatch, capsys):
    # Ctrl-C must exit cleanly (130), not dump a traceback, for any command.
    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("looptight.cli.cmd_doctor", boom)
    assert main(["doctor"]) == 130
    assert "interrupted" in capsys.readouterr().out.lower()


def test_main_prints_help_and_returns_zero_when_no_subcommand(capsys):
    # cli.py:394-396: if not args.command → print_help → return 0
    assert main([]) == 0


def test_run_banner_omits_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )
    main(["run", "--headless", "fix it", "--verify", "exit 0"])
    out = " ".join(capsys.readouterr().out.lower().split())  # collapse rich line-wrapping
    assert "budget" not in out


def test_run_exits_one_when_verify_never_passes(tmp_path, monkeypatch):
    # The primary command's failure exit code is a contract CI/scripts gate on:
    # a run that ends without a passing verify must return 1, not 0.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )
    assert main(["run", "--headless", "fix it", "--verify", "exit 1", "--max-iterations", "1"]) == 1


def test_next_prints_a_grounded_task(tmp_path, monkeypatch, capsys):
    # `looptight next` emits the top grounded task for the current session to do.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    _commit_fixture()
    assert main(["next"]) == 0
    assert "fix the timeout" in capsys.readouterr().out


def test_next_human_output_shows_acceptance_without_changing_json(
    tmp_path, monkeypatch, capsys
):
    # A person running `looptight next` should see the observable done-criterion,
    # not just the goal, while the machine `--json` decision stays unchanged.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")

    _commit_fixture()
    assert main(["next"]) == 0
    human = capsys.readouterr().out
    assert "fix the timeout" in human
    assert "Remove the marker" in human

    _reset_claims()  # a fresh session re-offers the same task; the prior `next` claimed it
    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "Remove the marker" in data["task"]["acceptance"]
    assert set(data) == {"schema_version", "command", "status", "task"}


def test_doctor_exit_code_and_json_reflect_readiness(tmp_path, monkeypatch, capsys):
    # `doctor` is scriptable: non-zero when the repo is unsafe to loop, zero when it
    # is ready, and its --json names the readiness tier.
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) != 0  # not a git repo and no verify command: unsafe
    capsys.readouterr()

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )
    assert main(["doctor"]) == 0  # verify set, clean git: safe to loop
    capsys.readouterr()

    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["readiness"]["tier"] in {"ready", "partial"}


def test_propose_empty_state_guides_new_dev_to_next_and_goal(tmp_path, monkeypatch, capsys):
    # A clean tree should not dead-end: point the newcomer at idea generation and goal mode.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    assert "No candidate tasks" in out
    assert "looptight next" in out
    assert "looptight goal" in out

    # The machine path on an empty tree is still a bare list.
    assert main(["propose", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_propose_header_pluralizes_on_count(tmp_path, monkeypatch, capsys):
    # The candidate-count header must read naturally: "1 candidate task" (singular)
    # and "2 candidate tasks" (plural), never the lazy "task(s)".
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    src = tmp_path / "src"
    src.mkdir()

    (src / "a.py").write_text("# TODO: fix one thing\n", encoding="utf-8")
    assert main(["propose"]) == 0
    one = capsys.readouterr().out
    assert "1 candidate task " in one
    assert "task(s)" not in one

    (src / "b.py").write_text("# TODO: fix another thing\n", encoding="utf-8")
    assert main(["propose"]) == 0
    two = capsys.readouterr().out
    assert "2 candidate tasks" in two
    assert "task(s)" not in two


def test_propose_reports_truncation_instead_of_silently_capping(tmp_path, monkeypatch, capsys):
    # With more candidates than the default --limit, the header must say "10 of N" and point at
    # --limit 0, not silently show 10 as if that were the whole backlog.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    src = tmp_path / "src"
    src.mkdir()
    body = "\n".join(f"def f{i}():  # TODO: task {i} needs attention" for i in range(25))
    (src / "a.py").write_text(body + "\n", encoding="utf-8")

    assert main(["propose"]) == 0  # default limit 10
    out = capsys.readouterr().out
    assert "10 of " in out  # honest "N of M" header
    assert "more not shown" in out
    assert "--limit 0" in out

    assert main(["propose", "--limit", "0"]) == 0  # unlimited: no truncation notice
    full = capsys.readouterr().out
    assert " of " not in full.splitlines()[0]  # header has no "N of M"
    assert "more not shown" not in full


def test_init_warns_when_verify_is_lint_only(tmp_path, monkeypatch, capsys):
    # A linter as the verify command passes even with broken logic; warn the new dev.
    from looptight import commands

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(commands, "detect_verify", lambda *a, **k: "ruff check")
    monkeypatch.setattr(commands, "detect_agent", lambda *a, **k: None)
    assert main(["init"]) == 0
    out = capsys.readouterr().out.lower()
    assert "ruff check" in out
    assert "behavior can still break" in out  # the lint-only risk note


def test_init_does_not_warn_for_a_unit_test_verify(tmp_path, monkeypatch, capsys):
    from looptight import commands

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(commands, "detect_verify", lambda *a, **k: "pytest -q")
    monkeypatch.setattr(commands, "detect_agent", lambda *a, **k: None)
    assert main(["init"]) == 0
    assert "note:" not in capsys.readouterr().out.lower()  # a real test gate needs no nag


def test_doctor_human_output_shows_readiness_tier_matching_exit(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert "readiness:" in out  # the tier is shown alongside the legacy setup line
    assert f"exit {code}" in out  # and it matches the real exit code


def test_next_human_output_does_not_stutter_the_evidence_label(tmp_path, monkeypatch, capsys):
    # A curated task carries its evidence marker inline; the stored field keeps the marker for
    # the parsers, but the human line must show one label and the bare path, not the marker twice.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    return 1\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    docs.joinpath("STATUS.md").write_text(
        "## Next\n\n1. Harden f. Evidence: src/a.py:1; Acceptance: a test covers it.\n\n## Rules\n"
    )
    _commit_fixture()
    assert main(["next"]) == 0
    human = capsys.readouterr().out
    assert "evidence: src/a.py:1" in human  # single label, bare path
    assert "Evidence: src/a.py" not in human  # the marker word is not repeated after the label


def test_next_human_output_falls_back_to_raw_evidence_without_a_marker(tmp_path, monkeypatch, capsys):
    # Ad-hoc signals (a TODO) have no evidence marker; the evidence line still shows the raw
    # detail so the fallback is not silently blanked.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    _commit_fixture()
    assert main(["next"]) == 0
    human = capsys.readouterr().out
    assert "evidence:" in human and "fix the timeout" in human


def test_doctor_explains_readiness_with_the_checks(tmp_path, monkeypatch, capsys):
    # The diagnostic must explain its readiness verdict, not just label it: a dirty worktree
    # should surface as a `readiness checks:` line (the same reasons `status` shows), so the
    # user does not have to run a second command to learn why readiness is unsafe/partial.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")  # uncommitted → dirty
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert "readiness checks:" in out, "doctor labels readiness but never explains it"
    assert "git " in out  # the git state (the reason) is named inline
    assert code == 1  # dirty → unsafe → non-zero, unchanged
    # `status` reports the groundedness of the generated `## Next` batch as a
    # self-improvement signal, without disturbing its existing keys.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# a\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "STATUS.md").write_text(
        "## Next\n\n1. Harden a. Evidence: src/a.py:1; Acceptance: it passes.\n"
    )

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["idea_quality"]["size"] == 1
    assert data["idea_quality"]["groundedness"] == 1.0
    assert "readiness" in data  # existing keys intact

    # An empty queue carries no idea_quality block.
    (docs / "STATUS.md").write_text("## Next\n\n_drained_\n")
    assert main(["status", "--json"]) == 0
    assert "idea_quality" not in json.loads(capsys.readouterr().out)


def test_next_human_output_guides_through_verify_and_commit(tmp_path, monkeypatch, capsys):
    # A new dev should see the whole loop from the task: implement, verify, commit on pass.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")

    _commit_fixture()
    assert main(["next"]) == 0
    human = capsys.readouterr().out.lower()
    assert "implement" in human
    assert "looptight verify" in human
    assert "commit" in human

    # The machine path stays prose-free: the guidance never enters the JSON.
    assert main(["next", "--json"]) == 0
    assert "commit" not in capsys.readouterr().out.lower()


def test_next_no_work_directs_idea_generation_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    assert main(["next"]) == 0
    out = capsys.readouterr().out
    assert "NO_WORK" in out
    assert "--no-ideas" in out  # the default offers idea generation rather than stopping


def test_next_no_work_points_at_configured_task_files(tmp_path, monkeypatch, capsys):
    # With a custom `tasks` config, discovery reads those files, not docs/STATUS.md — so the
    # empty-queue guidance must point at the configured files, not misdirect the user to STATUS.md.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\ntasks = ["NOTES.md"]\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    assert main(["next"]) == 0
    out = capsys.readouterr().out
    assert "NO_WORK" in out
    assert "NOTES.md" in out  # points at the configured file
    assert "docs/STATUS.md" not in out  # not the default it never reads

    # The auto-gen directive is suppressed (its planner targets docs/STATUS.md, which discovery
    # does not read here), so generated tasks can't land where `next` looks — JSON carries no directive.
    assert main(["next", "--json"]) == 0
    assert "directive" not in json.loads(capsys.readouterr().out)  # directive omitted when suppressed


def test_next_idea_gen_stays_on_when_custom_tasks_include_status_md(tmp_path, monkeypatch, capsys):
    # If the custom `tasks` list includes docs/STATUS.md, auto-gen is coherent (it targets a file
    # discovery reads), so the directive stays and the guidance points at STATUS.md as usual.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "true"\ntasks = ["docs/STATUS.md", "NOTES.md"]\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    assert main(["next", "--json"]) == 0
    assert "directive" in json.loads(capsys.readouterr().out)  # auto-gen stays coherent


def test_next_no_work_is_bare_with_no_ideas(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    assert main(["next", "--no-ideas"]) == 0
    assert capsys.readouterr().out.strip() == "NO_WORK"


def test_next_json_no_work_directs_idea_generation_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "no_work"
    assert data["directive"]["action"] == "generate_ideas"
    assert "docs/STATUS.md" in data["directive"]["prompt"]


def test_propose_eval_scores_the_generated_queue(tmp_path, monkeypatch, capsys):
    # `propose --eval` scores the generated docs/STATUS.md ## Next batch so its
    # grounding can be measured, not just trusted.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# a\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "STATUS.md").write_text(
        "## Next\n\n"
        "1. Harden a. Evidence: src/a.py:1; Acceptance: passes.\n"
        "2. Do x. Evidence: src/ghost.py:1; Acceptance: passes.\n"
    )

    assert main(["propose", "--eval", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "candidates" in data
    # The eval scores the RAW generated batch, not a grounding-filtered subset, so the
    # fabricated-evidence item is counted and lowers groundedness — surfacing it as honest
    # feedback instead of silently hiding it (which would peg groundedness at a useless 1.0).
    assert data["eval"]["size"] == 2
    assert data["eval"]["grounded"] == 1
    assert data["eval"]["groundedness"] == 0.5
    assert data["eval"]["bounded"] is True

    assert main(["propose", "--eval"]) == 0  # human output does not error
    assert "groundedness" in capsys.readouterr().out


def test_eval_line_formats_batch_score_fields():
    # protocol_commands.py:184 — _eval_line has no direct unit test; it is reached
    # only through cmd_propose --eval. This test pins all six output fields so a
    # format-string regression is caught without going through the full CLI path.
    from looptight.idea_eval import BatchScore
    from looptight.protocol_commands import _eval_line

    score = BatchScore(size=4, grounded=3, flexibility=2, distinct=4, bounded=True)
    line = _eval_line(score)
    assert "grounded 3/4" in line
    assert "0.75" in line          # groundedness
    assert "areas 2" in line
    assert "distinct 4" in line
    assert "bounded yes" in line


def test_next_json_contract_is_grounded_and_stable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")

    _commit_fixture()
    assert main(["next", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    _reset_claims()  # determinism is over committed code, not claim state; re-offer the task
    assert main(["next", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert first["schema_version"] == 1
    assert first["command"] == "next"
    assert first["status"] == "task"
    assert first["task"]["source"] == "todo"
    assert first["task"]["location"] == "src/a.py:1"
    assert "fix the timeout" in first["task"]["goal"]
    assert first["task"]["evidence"] == "# TODO: fix the timeout"
    assert "Remove the marker" in first["task"]["acceptance"]
    assert "idea_id" in first["task"]
    assert "suggested_verify" in first["task"]


def test_next_json_no_work_contract(tmp_path, monkeypatch, capsys):
    # With idea generation off, the no_work payload is the bare, stable contract.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    assert main(["next", "--json", "--no-ideas"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "schema_version": 1,
        "command": "next",
        "status": "no_work",
        "task": None,
    }


def test_next_json_trims_redundant_goal_for_grounded_status_task(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "# S\n\n## Next\n\n"
        "1. Cover the thing module. Evidence: src/thing.py:1; "
        "Acceptance: a test imports thing and passes.\n",
        encoding="utf-8",
    )

    _commit_fixture()
    assert main(["next", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)["task"]
    assert "Cover the thing module" in task["goal"]
    assert "Evidence:" not in task["goal"]  # grounding no longer duplicated into goal
    assert "Acceptance:" not in task["goal"]
    assert task["evidence"] == "Evidence: src/thing.py:1"
    assert "a test imports thing" in task["acceptance"]


def test_next_human_explains_task_selection(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "# S\n\n## Next\n\n"
        "1. Cover the thing module. Evidence: src/thing.py:1; "
        "Acceptance: a test imports thing and passes.\n",
        encoding="utf-8",
    )

    _commit_fixture()
    assert main(["next"]) == 0

    out = capsys.readouterr().out
    assert "selected task:" in out
    assert "why: status-next from docs/STATUS.md" in out
    assert "evidence: src/thing.py:1" in out  # single label, bare parsed path (no doubled marker)
    assert "Evidence: src/thing.py" not in out
    assert "acceptance: a test imports thing and passes." in out
    assert "next: implement the task, run `looptight verify`, and commit only if it passes" in out


def test_next_human_output_notes_an_active_build_goal(tmp_path, monkeypatch, capsys):
    # `status` points at `goal next` when a goal is active; `next` (evidence
    # discovery) should likewise note the active goal so a user who set one is not
    # left wondering why `next` ignored it. The note prints regardless of outcome.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "f.py").write_text("x = 1  # TODO: fix\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=tmp_path, check=True)

    assert main(["next"]) == 0
    assert "goal next" not in capsys.readouterr().out  # no goal -> no note

    main(["goal", "build a thing"])
    capsys.readouterr()
    assert main(["next"]) == 0
    assert "goal next" in capsys.readouterr().out  # active goal -> note present


def test_goal_set_refuses_outside_a_git_repo(tmp_path, monkeypatch, capsys):
    # Setting a goal outside Git must not crash with a traceback (a goal is stored in Git);
    # it degrades like every sibling path — a JSON error envelope under --json, exit 2.
    from looptight.goal import read_goal

    monkeypatch.chdir(tmp_path)  # not a git repo

    assert main(["goal", "build a thing", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error"
    assert data["error"] == "not_git"

    assert main(["goal", "build a thing"]) == 2  # human form clean too
    assert "git repository" in capsys.readouterr().out.lower()
    assert read_goal(tmp_path) is None  # nothing was written


def test_goal_set_guides_to_the_first_increment(tmp_path, monkeypatch, capsys):
    # Plain `goal set` should not leave the user wondering "now what?" — it names the next step
    # (like init/next do), while `--continuous` still prints the full hands-off driver recipe.
    # Force claude detection so the Claude-Code-specific recipe line is deterministic: it is gated
    # on `detect_agent() == "claude"`, which otherwise depends on whether `claude` is on PATH (true
    # in a Claude Code session, false in CI) — the difference that made this test pass locally but
    # fail in CI.
    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i", "--allow-empty"],
        cwd=tmp_path, check=True,
    )

    assert main(["goal", "build a calculator"]) == 0
    out = capsys.readouterr().out
    assert "goal set: build a calculator" in out
    assert "looptight goal next" in out  # the first-increment pointer

    assert main(["goal", "build a calculator", "--continuous"]) == 0
    assert "/loop until: looptight goal check" in capsys.readouterr().out  # recipe unchanged


def test_goal_continuous_omits_loop_hint_for_non_claude_agent(tmp_path, monkeypatch, capsys):
    # When detect_agent returns a non-claude value (e.g. "codex"), the driver recipe must
    # NOT include the Claude-specific `/loop until:` hint and must still include the
    # generic `looptight goal next` instruction.
    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda *a, **k: "codex")
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i", "--allow-empty"],
        cwd=tmp_path, check=True,
    )

    assert main(["goal", "build a calculator", "--continuous"]) == 0
    out = capsys.readouterr().out
    assert "/loop until:" not in out
    assert "looptight goal next" in out


def test_goal_set_rejects_an_empty_vision(tmp_path, monkeypatch, capsys):
    # An empty/whitespace vision is rejected at the boundary, not persisted as a vacuous goal
    # that would hand the host a build directive with no stated vision.
    from looptight.goal import read_goal

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    assert main(["goal", "   ", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["error"] == "empty_vision"
    assert read_goal(tmp_path) is None  # no vacuous goal written

    assert main(["goal", "build a real thing"]) == 0  # a real vision still sets a goal
    assert read_goal(tmp_path) is not None


def test_next_and_swarm_parsers_accept_no_ideas():
    assert build_parser().parse_args(["next", "--no-ideas"]).no_ideas is True
    assert build_parser().parse_args(["swarm", "--headless", "--no-ideas"]).no_ideas is True


def test_next_json_reads_each_configured_task_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'tasks = ["TODO.md", "docs/BACKLOG.md"]\n', encoding="utf-8"
    )
    (tmp_path / "TODO.md").write_text(
        "1. First configured task. Acceptance: first passes.\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "BACKLOG.md").write_text(
        "# Backlog\n\n## Ready\n\n"
        "1. Second configured task. Acceptance: second passes.\n",
        encoding="utf-8",
    )

    assert {candidate.location for candidate in propose(tmp_path, limit=0)} == {
        "TODO.md:1",
        "docs/BACKLOG.md:5",
    }

    _commit_fixture()
    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "task"
    assert data["task"]["location"] == "TODO.md:1"
    assert "First configured task" in data["task"]["goal"]


def test_next_json_returns_no_work_for_empty_configured_sources(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'tasks = ["TODO.md"]\n', encoding="utf-8"
    )
    (tmp_path / "TODO.md").write_text("# No executable tasks\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: ignored fallback signal\n")

    _commit_fixture()
    assert main(["next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_work"


def test_next_json_refuses_dirty_git_worktree_before_claim(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "docs").mkdir()
    status = tmp_path / "docs" / "STATUS.md"
    status.write_text(
        "## Next\n\n1. Fix it. Acceptance: verification passes.\n",
        encoding="utf-8",
    )

    assert main(["next", "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "command": "next",
        "status": "error",
        "task": None,
        "error": "dirty_worktree",
    }
    assert not (tmp_path / ".git" / "looptight" / "claims").exists()


def test_next_human_error_for_dirty_worktree_is_actionable(tmp_path, monkeypatch, capsys):
    # The human path must explain a dirty worktree and suggest an action, not just
    # echo the machine error code the --json path carries.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Fix it. Acceptance: verification passes.\n",
        encoding="utf-8",
    )

    assert main(["next"]) == 2
    out = capsys.readouterr().out
    assert "ERROR: dirty_worktree" not in out  # no bare machine code
    lowered = out.lower()
    assert "worktree" in lowered
    assert "commit" in lowered or "stash" in lowered


def test_next_json_claims_from_clean_git_worktree(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Fix it. Acceptance: verification passes.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "docs/STATUS.md"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Looptight Test",
            "-c",
            "user.email=test@looptight.dev",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )

    assert main(["next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "task"


def test_same_worktree_run_ids_claim_distinct_tasks_and_status_tracks_owner(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n"
        "1. First task. Evidence: docs/STATUS.md:1; Acceptance: first passes.\n"
        "2. Second task. Evidence: docs/STATUS.md:1; Acceptance: second passes.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "docs/STATUS.md"], check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", "commit", "-qm", "tasks"],
        check=True,
    )

    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-a")
    assert main(["next", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)["task"]["id"]
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-b")
    assert main(["next", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)["task"]["id"]

    assert first != second
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-a")
    assert main(["status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["claimed_task"] == first
    assert status["active_claims"] == 2


def test_status_human_does_not_print_claimed_directive_twice(tmp_path, monkeypatch, capsys):
    # With a live claim the human status printed the full multi-sentence directive twice: once on
    # `next: continue your claimed task: <directive>` and again on the `session:` panel line. The
    # panel carries the directive (like the goal line in goal mode), so the human next: line stays
    # terse. The JSON next_action keeps the full directive for machines.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: handle the empty input case\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-z")
    assert main(["next", "--json"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    next_line = [ln for ln in out.splitlines() if ln.startswith("next:")][0]
    session_line = [ln for ln in out.splitlines() if ln.startswith("session:")][0]
    assert "continue your claimed task" in next_line
    assert "empty input" not in next_line  # the directive is not repeated on the next: line
    assert "empty input" in session_line  # the panel carries it once

    assert main(["status", "--json"]) == 0
    assert "empty input" in json.loads(capsys.readouterr().out)["next_action"]  # JSON unchanged


def test_status_next_action_names_the_claimed_task_goal(tmp_path, monkeypatch, capsys):
    # status should say what you're working on, not the opaque claim fingerprint.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: handle the empty input case\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-x")  # one session id across next + status

    assert main(["next", "--json"]) == 0  # claim the TODO task
    capsys.readouterr()

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["claimed_task"] is not None  # the machine-stable fingerprint is unchanged
    assert "empty input" in data["next_action"]  # the human action names the goal
    assert "continue" in data["next_action"].lower()


def test_status_recognizes_a_claim_from_a_separate_invocation(tmp_path, monkeypatch, capsys):
    # A claim made by `next` in one invocation must be recognized by `status` in a SEPARATE
    # invocation (different run id, as in real shell usage) — the next-action should say
    # "continue your claimed task", not "run looptight next", matching the owner-scoped panel.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: handle the empty input case\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )

    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-claim")  # the `next` invocation claims the task
    assert main(["next", "--json"]) == 0
    capsys.readouterr()

    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "run-status")  # a DIFFERENT later `status` invocation
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["claimed_task"] is not None  # the worktree's claim is recognized (owner-scoped)
    assert "continue" in data["next_action"].lower()  # not "run looptight next"
    assert "empty input" in data["next_action"]  # names the claimed goal


def test_next_no_work_clears_claim_when_task_disappears(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "docs").mkdir()
    status = tmp_path / "docs" / "STATUS.md"
    status.write_text(
        "## Next\n\n1. Fix it. Acceptance: verification passes.\n",
        encoding="utf-8",
    )
    commit = [
        "git",
        "-c",
        "user.name=Looptight Test",
        "-c",
        "user.email=test@looptight.dev",
        "commit",
        "-qm",
    ]
    subprocess.run(["git", "add", "docs/STATUS.md"], check=True)
    subprocess.run([*commit, "task"], check=True)
    assert main(["next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "task"

    status.write_text("## Next\n\n_No work._\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/STATUS.md"], check=True)
    subprocess.run([*commit, "complete task"], check=True)

    assert main(["next", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_work"
    assert main(["status", "--json"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["active_claims"] == 0
    assert status_payload["claimed_task"] is None


def test_status_json_is_read_only_and_actionable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert data["command"] == "status"
    assert data["validation"] == "missing"
    assert data["workspace"] == "not_git"
    assert data["claimed_task"] is None
    assert data["readiness"]["tier"] == "unsafe"
    assert data["readiness"]["checks"]["git"] == "not_git"
    assert "looptight init" in data["next_action"]
    assert list(tmp_path.iterdir()) == []


def test_human_readiness_checks_do_not_leak_snake_case_status(tmp_path, monkeypatch, capsys):
    # Outside a git repo the readiness/concurrency checks include the internal `not_git`
    # status. Human output must read it as prose ("not a git repo"), matching the rest of
    # the doctor/status lines, not leak the snake_case enum token. The JSON keeps `not_git`.
    monkeypatch.chdir(tmp_path)

    assert main(["status"]) == 0  # read-only human report
    human = capsys.readouterr().out
    assert "not_git" not in human, "snake_case status token leaked into human output"
    assert "not a git repo" in human

    assert main(["doctor"]) == 1  # non-git → unsafe
    doctor = capsys.readouterr().out
    assert "not_git" not in doctor
    assert "not a git repo" in doctor

    # The machine contract is unchanged — JSON consumers still see the enum token.
    main(["status", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["readiness"]["checks"]["git"] == "not_git"
    assert data["workspace"] == "not_git"


def test_human_status_and_doctor_surface_configured_policy(tmp_path, monkeypatch, capsys):
    # Safety rails (no_direct_push, max_changed_files, protected_paths, allowed_verify_commands)
    # were visible only in --json. A user who configures them must be able to confirm they took
    # hold in the human status/doctor output.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "true"\nno_direct_push = true\nmax_changed_files = 5\n'
        'protected_paths = ["src/secrets/**", ".github/**"]\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
        cwd=tmp_path, check=True,
    )

    assert main(["status"]) == 0
    status_out = capsys.readouterr().out
    assert "policy: no direct push · max 5 changed files · 2 protected paths" in status_out

    assert main(["doctor"]) in (0, 1)
    assert "policy: no direct push" in capsys.readouterr().out

    # A repo with no policy configured shows no policy line (no noise).
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    assert main(["status"]) == 0
    assert "policy:" not in capsys.readouterr().out


def test_policy_line_includes_allowed_verify_commands_count(tmp_path, monkeypatch, capsys):
    # `policy_line`'s allowed_verify_commands branch (protocol_commands.py:978) was uncovered:
    # a user who configures an allowlist must see it confirmed in human status output.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "true"\nallowed_verify_commands = ["pytest -q"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
        cwd=tmp_path, check=True,
    )
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "1 allowed verify command" in out


def test_status_readiness_reports_ready_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\ntasks = ["docs/STATUS.md"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("## Next\n\n_No work._\n", encoding="utf-8")
    subprocess.run(["git", "add", ".looptight.toml", "docs/STATUS.md"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    (tmp_path / ".git" / "looptight").mkdir(parents=True)
    (tmp_path / ".git" / "looptight" / "coordinator-format.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda: "codex")

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["readiness"]["tier"] == "ready"
    assert data["readiness"]["next_remediation"] == "run `looptight next --json`"
    assert data["readiness"]["checks"] == {
        "verify": "configured",
        "git": "clean",
        "coordinator": "active",
        "task_sources": "configured",
        "agent": "available",
    }


def test_verify_reports_config_and_policy_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    # A malformed config makes `verify` report a config error and exit 2 (human + json).
    (tmp_path / ".looptight.toml").write_text('verify = ["bad"]\n', encoding="utf-8")
    assert main(["verify"]) == 2
    assert "config error:" in capsys.readouterr().out
    assert main(["verify", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"

    # A protected-path change makes `verify` report a policy error and exit 2 (human).
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nprotected_paths = ["secret.py"]\n', encoding="utf-8"
    )
    (tmp_path / "secret.py").write_text("x\n", encoding="utf-8")
    assert main(["verify"]) == 2
    assert "policy error:" in capsys.readouterr().out


def test_readiness_remediation_for_missing_agent():
    # When verify/git/task_sources are healthy but no agent CLI is installed, readiness
    # guidance must point the user at installing an agent — the lone remediation branch
    # the status integration tests do not reach.
    from looptight.protocol_commands import _readiness_remediation

    checks = {
        "verify": "configured",
        "git": "clean",
        "task_sources": "configured",
        "agent": "missing",
    }
    assert _readiness_remediation(checks, "fallback") == "install a supported agent CLI"


def test_readiness_remediation_priority_branches():
    from looptight.protocol_commands import _readiness_remediation

    base = {"verify": "configured", "git": "clean", "task_sources": "configured", "agent": "ok"}

    assert _readiness_remediation({**base, "verify": "missing"}, "fb") == "run `looptight init`"
    assert _readiness_remediation({**base, "git": "not_git"}, "fb") == "run inside a Git repository"
    assert _readiness_remediation({**base, "git": "dirty"}, "fb") == "review changes and run `looptight verify --json`"
    assert _readiness_remediation({**base, "task_sources": "missing"}, "fb") == "add grounded tasks or configure `tasks` in .looptight.toml"


def test_status_readiness_reports_partial_repo_with_remediation(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")
    subprocess.run(["git", "add", ".looptight.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda: None)

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["readiness"]["tier"] == "partial"
    assert data["readiness"]["checks"]["coordinator"] == "active"  # DB is the store in any git repo
    assert data["readiness"]["checks"]["task_sources"] == "missing"
    assert data["readiness"]["checks"]["agent"] == "missing"
    # The coordinator no longer gates readiness, so remediation points at the real
    # gaps (task sources, then agent), not at `migrate`.
    assert data["readiness"]["next_remediation"] == (
        "add grounded tasks or configure `tasks` in .looptight.toml"
    )


def test_status_human_prints_readiness_tier(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")
    subprocess.run(["git", "add", ".looptight.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda: None)

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "readiness: partial" in out
    assert "readiness next: add grounded tasks or configure `tasks` in .looptight.toml" in out


def test_status_json_classifies_common_verifier_quality(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    cases = {
        "pytest -q": "unit",
        "ruff check": "lint-only",
        "npm test": "unit",
        "make test": "custom/unknown",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected
        assert data["verifier_quality"]["risk"]


def test_status_json_classifies_biome_and_oxlint_as_lint_only(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    for command in ("biome check .", "oxlint src/"):
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == "lint-only", command
        assert data["verifier_quality"]["risk"]


def test_status_json_classifies_mypy_and_pyright_as_lint_only(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    for command in ("mypy src/", "pyright"):
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == "lint-only", command
        assert data["verifier_quality"]["risk"]


def test_status_json_ignores_negated_marker_deselection(
    tmp_path, monkeypatch, capsys
):
    # A pytest `-m "not integration"` / `not e2e` deselection EXCLUDES those
    # markers, so the command is a unit run — it must not be read as an
    # integration/e2e verifier off the incidental substring. A real path- or
    # marker-based integration/e2e command is unaffected.
    monkeypatch.chdir(tmp_path)
    cases = {
        'pytest -m "not integration"': "unit",
        'pytest -m "not e2e"': "unit",
        'pytest -m "not playwright"': "unit",   # excludes playwright, still a unit run
        'pytest -m "not cypress"': "unit",      # excludes cypress, still a unit run
        "pytest tests/integration_suite": "integration",  # real integration, unchanged
        "playwright test": "e2e",  # real e2e, unchanged
        "cypress run": "e2e",      # real e2e, unchanged
    }
    for command, expected in cases.items():
        # single-quoted TOML literal: the commands contain double quotes
        (tmp_path / ".looptight.toml").write_text(f"verify = '{command}'\n")
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_status_json_classifies_detected_runners_as_unit(
    tmp_path, monkeypatch, capsys
):
    # Every unambiguous single-runner test command that detect_verify auto-selects
    # must classify as `unit`, not `custom/unknown` — otherwise a Rust/Go/.NET/JVM
    # user is told their own detected test command is an unknown verifier. make/just
    # recipes stay custom/unknown (arbitrary), asserted by the common-quality test.
    monkeypatch.chdir(tmp_path)
    cases = {
        "cargo test": "unit",
        "go test ./...": "unit",
        "deno test": "unit",
        "mix test": "unit",
        "swift test": "unit",
        "dotnet test": "unit",
        "gradle test": "unit",
        "./gradlew test": "unit",
        "mvn test": "unit",
        "./mvnw test": "unit",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_status_json_classifies_bun_node_test_and_mocha_as_unit(
    tmp_path, monkeypatch, capsys
):
    # bun test, node --test, mocha, pnpm test, and yarn test are mainstream
    # unambiguous test runners that must classify as `unit`, not `custom/unknown`.
    # pnpm/yarn: removing either from the unit list in protocol_commands.py:877
    # would cause affected projects to land in `custom/unknown`, suppressing the
    # `unit`-tier risk message — this test is the mutation guard.
    monkeypatch.chdir(tmp_path)
    cases = {
        "bun test": "unit",
        "node --test": "unit",
        "mocha": "unit",
        "pnpm test": "unit",
        "yarn test": "unit",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_status_json_classifies_ruby_php_haskell_runners_as_unit(
    tmp_path, monkeypatch, capsys
):
    # Ruby (rspec/bundle exec rspec), PHP (phpunit/pest/php artisan test), and
    # Haskell (stack test/cabal test) are well-known unit test runners that a user
    # may manually configure. They must classify as `unit`, not `custom/unknown` —
    # removing any one from the list in protocol_commands.py would silently degrade
    # the risk message for that ecosystem; this test is the mutation guard.
    monkeypatch.chdir(tmp_path)
    cases = {
        "rspec": "unit",
        "rspec spec": "unit",
        "bundle exec rspec": "unit",
        "bundle exec rspec spec": "unit",
        "phpunit": "unit",
        "vendor/bin/phpunit": "unit",
        "pest": "unit",
        "vendor/bin/pest": "unit",
        "php artisan test": "unit",
        "stack test": "unit",
        "cabal test": "unit",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_status_json_classifies_crystal_spec_as_unit(tmp_path, monkeypatch, capsys):
    # crystal spec is Crystal's single unambiguous test runner; it must classify
    # as `unit`, not `custom/unknown`, so a Crystal project configured via
    # `detect_verify` or manually reports the correct verifier-quality tier.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "crystal spec"\n')
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["verifier_quality"]["classification"] == "unit"


def test_status_json_classifies_tests_plus_lint_as_unit_not_lint_only(
    tmp_path, monkeypatch, capsys
):
    # A verify command that runs tests AND a linter must classify by the stronger
    # signal (the tests), not short-circuit to lint-only. Regression: the lint
    # check ran before the unit check, so this repo's own
    # `pytest && ruff check` reported lint-only despite running pytest.
    monkeypatch.chdir(tmp_path)
    cases = {
        "uv run pytest -q && uv run ruff check": "unit",
        "ruff check": "lint-only",  # pure lint still lint-only
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_verifier_quality_pdm_run_pytest_is_unit(
    tmp_path, monkeypatch, capsys
):
    # pdm run pytest contains "pytest", so it's already unit-level via the substring
    # scan. Pin this so a refactor that adds an explicit pdm prefix list doesn't
    # accidentally break the existing path by rearranging checks.
    monkeypatch.chdir(tmp_path)
    cases = {
        "uv run pytest -q": "unit",
        "poetry run pytest -q": "unit",
        "pdm run pytest -q": "unit",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )


def test_status_json_classifies_e2e_and_integration_verifier_quality(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    cases = {
        "playwright test": "e2e",
        "cypress run": "e2e",
        "pytest e2e": "e2e",
        "pytest integration": "integration",
        "run-integration-tests.sh": "integration",
    }
    for command, expected in cases.items():
        (tmp_path / ".looptight.toml").write_text(f'verify = "{command}"\n')
        assert main(["status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["verifier_quality"]["classification"] == expected, (
            f"expected {expected!r} for {command!r}, "
            f"got {data['verifier_quality']['classification']!r}"
        )
        assert data["verifier_quality"]["risk"]


def test_status_json_classifies_missing_verifier_quality(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["verifier_quality"]["classification"] == "none"
    assert "No verifier" in data["verifier_quality"]["risk"]


def test_status_human_explains_verifier_quality_risk(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "ruff check"\n')

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "verifier quality: lint-only" in out
    assert "only protects style/static checks" in out


def test_status_json_reports_safe_concurrency_when_coordinator_active(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".git" / "looptight").mkdir(parents=True)
    (tmp_path / ".git" / "looptight" / "coordinator-format.json").write_text("{}\n", encoding="utf-8")

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["concurrency"]["status"] == "safe"
    assert data["concurrency"]["scope"] == "local-filesystem"
    assert data["concurrency"]["checks"]["coordinator"] == "active"
    assert data["concurrency"]["next_remediation"] == "none"


def test_status_json_reports_degraded_concurrency_for_active_work(
    tmp_path, monkeypatch, capsys
):
    from looptight.coordinator import Coordinator

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    coordinator = Coordinator.open(tmp_path)
    assert coordinator is not None
    coordinator.activate_from_legacy()
    run = coordinator.start_run("test", run_id="worker-a")
    coordinator.claim(
        [{"id": "task-a", "goal": "do", "source": "status-next", "location": None}],
        run.id,
        ttl_s=60,
    )
    coordinator.close()

    assert main(["status", "--json"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["concurrency"]["status"] == "degraded"
    assert data["concurrency"]["checks"]["active_leases"] == 1
    assert data["concurrency"]["next_remediation"] == "wait for active coordinator work to drain"


def test_status_concurrency_is_safe_in_plain_git_repo(tmp_path, monkeypatch, capsys):
    # The SQLite coordinator is the claim store in any git repo, so a plain repo
    # with no live legacy claims is concurrency-safe even before `migrate` runs.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "concurrency: safe" in out
    assert "run `looptight migrate`" not in out  # nothing to fence, no migrate prompt


def test_status_suppresses_concurrency_next_for_own_only_claim(tmp_path, monkeypatch, capsys):
    # A solo user whose own single claim is the only active coordinator work should not see
    # "concurrency next: wait for active coordinator work to drain" contradicting the authoritative
    # "next: continue your claimed task" below it. The concurrency status line itself still shows.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: handle the empty input case\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "solo")
    assert main(["next", "--json"]) == 0  # claim the only task
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "concurrency: degraded" in out  # the status itself is still reported
    assert "wait for active coordinator work to drain" not in out  # the contradiction is gone
    assert "continue your claimed task" in out  # the authoritative action remains


def test_status_concurrency_unsafe_only_with_live_legacy_claims(
    tmp_path, monkeypatch, capsys
):
    # The only concurrency threat is live legacy file claims racing the coordinator;
    # those make status unsafe with a fence-via-migrate remediation.
    from looptight.claims import ClaimStore, claim_dir

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    cdir = claim_dir(tmp_path)
    assert cdir is not None
    ClaimStore(cdir, "legacy-owner").select([{"id": "t1"}])  # writes a live legacy claim

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "concurrency: unsafe" in out
    assert "looptight migrate" in out  # fence the live legacy claims


def test_status_human_shows_verify_command_without_changing_json(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "make check"\n')

    assert main(["status"]) == 0
    human = capsys.readouterr().out
    assert "verify: make check" in human

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {
        "schema_version",
        "command",
        "validation",
        "workspace",
        "claimed_task",
        "active_claims",
        "next_action",
        "readiness",
        "verifier_quality",
        "concurrency",
        "coordination_scope",
        "policy",
    }
    assert "verify" not in data


def test_doctor_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) != 0  # empty, non-git dir is unsafe to loop


def test_doctor_reports_config_path_when_present(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')
    assert main(["doctor"]) != 0  # config present but not a git repo: unsafe
    out = capsys.readouterr().out
    assert ".looptight.toml" in out


def test_doctor_reports_no_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) != 0  # no config and not a git repo: unsafe
    out = capsys.readouterr().out.lower()
    assert "default" in out  # "none (using defaults)"


def test_doctor_hints_when_prerequisites_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # No verify command can be detected (empty dir) and no agent on PATH.
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)
    assert main(["doctor"]) != 0  # not a git repo and no verify: unsafe to loop
    out = capsys.readouterr().out
    assert "looptight init" in out  # remediation for missing verify
    assert "install one of" in out  # remediation for missing agent


def test_doctor_omits_hints_when_prerequisites_present(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    assert main(["doctor"]) != 0  # verify + agent present, but not a git repo: unsafe
    out = capsys.readouterr().out
    assert "hint:" not in out  # both present → existing lines unchanged


def test_doctor_shows_migrate_hint_when_live_legacy_claims_exist(tmp_path, monkeypatch, capsys):
    # cmd_doctor line 452: the `looptight migrate` hint only prints when
    # has_live_claim is True and the workspace is a git repo (git_ready=True).
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x", "--allow-empty"],
        cwd=tmp_path, check=True,
    )
    monkeypatch.setattr("looptight.commands.has_live_claim", lambda *a, **k: True)
    main(["doctor"])
    out = capsys.readouterr().out
    assert "looptight migrate" in out


def test_doctor_guides_setup_without_writing_or_starting_agents(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)

    assert main(["doctor"]) != 0  # empty, non-git dir: unsafe to loop

    out = capsys.readouterr().out
    assert "setup: not ready" in out
    assert "coordinator: not a git repo" in out
    assert "setup next: run `looptight init --integrate`" in out
    assert list(tmp_path.iterdir()) == []


def test_doctor_guides_ready_repository_to_next_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")
    subprocess.run(["git", "add", ".looptight.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    (tmp_path / ".git" / "looptight").mkdir(parents=True)
    (tmp_path / ".git" / "looptight" / "coordinator-format.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "codex")

    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert main(["doctor"]) == 0
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    out = capsys.readouterr().out
    assert "setup: ready" in out
    assert "coordinator: active" in out
    assert "setup next: run `looptight next --json`" in out
    assert after == before


def test_doctor_solo_setup_is_ready_with_active_coordinator(tmp_path, monkeypatch, capsys):
    # `next` leases through the coordinator DB in any git repo, so doctor reports
    # the coordinator active. With no live legacy claims there is nothing to fence,
    # so migrate is not suggested and is never a blocking `setup next`.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "codex")

    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "coordinator: active" in out  # the coordinator DB is the claim store
    assert "setup: ready" in out
    assert "setup next: run `looptight next --json`" in out
    assert "looptight migrate" not in out  # no live legacy claims, nothing to fence


def test_malformed_config_exits_cleanly_not_traceback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest"\nbad = = toml\n')
    # A broken config must surface as a clean exit code, not an uncaught traceback.
    assert main(["doctor"]) == 2


def test_json_commands_emit_a_json_envelope_on_config_error(tmp_path, monkeypatch, capsys):
    # A malformed config must not break the --json contract: a --json command emits a
    # parseable error envelope, not a plain-text "config error" line that no JSON consumer
    # can read. The human path still prints the readable detail.
    import subprocess as _sp

    monkeypatch.chdir(tmp_path)
    _sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # cmd_next needs a git repo to reach load_config
    (tmp_path / ".looptight.toml").write_text('verify = "pytest\n')  # unterminated string

    for command in ("status", "doctor", "next"):
        assert main([command, "--json"]) == 2
        data = json.loads(capsys.readouterr().out)
        assert data["command"] == command
        assert data["status"] == "error"
        assert data["error"] == "config_error"

    assert main(["status"]) == 2  # human path keeps the readable message
    assert "config error:" in capsys.readouterr().out


def test_version_exits_zero(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0


def test_verify_records_the_verdict_for_the_session_view(tmp_path, monkeypatch):
    # verify writes its verdict so `looptight ui`'s session view can show the loop's key signal.
    from looptight.ui import read_verdict

    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "exit 0"]) == 0
    assert read_verdict(tmp_path) == "pass"
    assert main(["verify", "--verify", "exit 1"]) == 1
    assert read_verdict(tmp_path) == "fail"  # latest verdict wins


def test_verify_passing_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "exit 0"]) == 0


def test_verify_human_explains_result_and_changed_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")

    assert main(["verify", "--verify", "exit 0"]) == 0

    out = capsys.readouterr().out
    assert "verify: PASS (exit 0)" in out  # the headline carries the verdict (no redundant echo)
    assert "verifier result:" not in out  # the duplicate lowercase verdict line is gone
    assert "changed files: tracked.txt" in out
    assert "next: review the diff, update status, then commit" in out


def test_verify_failing_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "exit 1"]) == 1


def test_verify_no_command_returns_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify"]) == 2


def test_verify_json_pass_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "printf 'SCORE: 0.75'", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == 1
    assert data["command"] == "verify"
    assert data["status"] == "pass"
    assert data["exit_code"] == 0
    assert data["score"] == 0.75
    assert data["error"] is None


def test_verify_json_fail_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "printf broken; exit 3", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "fail"
    assert data["exit_code"] == 3
    assert data["output"] == "broken"


def test_verify_json_missing_executable_is_machine_readable_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "this-binary-does-not-exist-xyz", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error"
    assert data["exit_code"] == 127
    assert data["error"] == "launch_error"


def test_verify_json_configuration_error_is_machine_readable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error"
    assert data["exit_code"] is None
    assert "No verify command" in data["output"]


def test_verify_json_refuses_protected_path_changes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nprotected_paths = ["secrets/"]\n',
        encoding="utf-8",
    )
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "token.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", ".looptight.toml", "secrets/token.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    (tmp_path / "secrets" / "token.txt").write_text("new\n", encoding="utf-8")

    assert main(["verify", "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "protected path" in payload["output"]
    assert "secrets/token.txt" in payload["output"]


def test_verify_json_refuses_protected_path_rename(tmp_path, monkeypatch, capsys):
    # Renaming/moving a protected file must be refused too: a rename removes the file
    # from its protected location, so it cannot be allowed to slip past the gate.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nprotected_paths = ["src/secret.py"]\n', encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "secret.py").write_text("secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )
    subprocess.run(["git", "mv", "src/secret.py", "src/moved.py"], check=True)

    assert main(["verify", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "protected path" in payload["output"]


def test_changed_file_list_splits_renames_and_unquotes(tmp_path, monkeypatch):
    # The policy parser must yield both sides of a rename and strip git's quoting,
    # so a protected path is matched regardless of how git formats the entry.
    from looptight import protocol_commands

    def fake_run(*args, **kwargs):
        class R:
            returncode = 0
            stdout = (
                "R  src/secret.py -> src/moved.py\n"
                ' M "with space.py"\n'
                "?? plain.py\n"
            )
        return R()

    monkeypatch.setattr(protocol_commands.subprocess, "run", fake_run)
    files = protocol_commands._changed_file_list(tmp_path)
    assert "src/secret.py" in files  # old side of the rename
    assert "src/moved.py" in files   # new side of the rename
    assert "with space.py" in files  # quotes stripped
    assert "plain.py" in files


def test_changed_entries_skips_short_git_status_lines(tmp_path, monkeypatch):
    # protocol_commands.py:392-393 — the `if len(line) <= 3: continue` guard skips lines
    # that are too short to contain a path (e.g. a bare "??" or " M " with no path). This
    # guard was dead in all prior tests, which only injected well-formed 4+-char lines.
    from looptight import protocol_commands

    def fake_run(*args, **kwargs):
        class R:
            returncode = 0
            # "??" is 2 chars (≤ 3) → skipped; " M src/a.py" is a normal 2-char status + space + path
            stdout = "??\n M src/a.py\n"
        return R()

    monkeypatch.setattr(protocol_commands.subprocess, "run", fake_run)
    entries = protocol_commands._changed_entries(tmp_path)
    assert entries == [["src/a.py"]]  # the short "??" line is skipped, normal line kept


def test_unquote_git_path_strips_surrounding_quotes_and_passes_unquoted():
    # protocol_commands.py:415 — git quotes paths containing special chars in "...";
    # the function must strip the outer double-quotes and pass unquoted paths through.
    from looptight.protocol_commands import _unquote_git_path

    assert _unquote_git_path('"path with spaces.py"') == "path with spaces.py"
    assert _unquote_git_path('"src/a.py"') == "src/a.py"
    assert _unquote_git_path("plain.py") == "plain.py"
    assert _unquote_git_path('"') == '"'  # single quote char — not stripped (len < 2 rule)
    assert _unquote_git_path("") == ""


def test_verify_json_refuses_glob_protected_path_changes(tmp_path, monkeypatch, capsys):
    # A glob pattern in protected_paths must actually protect matching files, not
    # silently fail open (the `*` implies globbing).
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nprotected_paths = ["config/*", "*.env"]\n',
        encoding="utf-8",
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "app.conf").write_text("old\n", encoding="utf-8")
    (tmp_path / "prod.env").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        check=True,
    )

    # A change to a glob-protected file is refused.
    (tmp_path / "config" / "app.conf").write_text("new\n", encoding="utf-8")
    assert main(["verify", "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "protected path" in payload["output"]
    subprocess.run(["git", "checkout", "config/app.conf"], check=True)

    # The `*.env` glob protects an env file too.
    (tmp_path / "prod.env").write_text("A=2\n", encoding="utf-8")
    assert main(["verify", "--json"]) == 2
    assert "protected path" in json.loads(capsys.readouterr().out)["output"]
    subprocess.run(["git", "checkout", "prod.env"], check=True)

    # A non-matching file change still passes.
    (tmp_path / "src.py").write_text("y = 2\n", encoding="utf-8")
    assert main(["verify", "--json"]) == 0


def test_verify_json_refuses_command_not_in_allowlist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nallowed_verify_commands = ["pytest -q"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".looptight.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )

    assert main(["verify", "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "not allowed by policy" in payload["output"]
    assert "exit 0" in payload["output"]


def test_verify_allowlist_match_ignores_surrounding_whitespace(tmp_path, monkeypatch, capsys):
    # An allowed command passed with incidental surrounding whitespace must match the allowlist
    # (the resolved command is trimmed), not be spuriously rejected.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "true"\nallowed_verify_commands = ["true"]\n', encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    assert main(["verify", "--verify", "  true  "]) == 0  # allowed despite the whitespace
    assert "PASS" in capsys.readouterr().out


def test_max_changed_files_counts_a_rename_as_one_file(tmp_path, monkeypatch):
    # A staged rename is `R  old -> new`: one changed file, two paths. The
    # protected-path scan needs both paths, but the max_changed_files COUNT must
    # treat the rename as a single file — otherwise renaming one file under
    # max_changed_files=1 is wrongly blocked.
    from types import SimpleNamespace

    from looptight import protocol_commands

    def fake_run(*args, **kwargs):
        class R:
            returncode = 0
            stdout = "R  src/a.py -> src/b.py\n"

        return R()

    monkeypatch.setattr(protocol_commands.subprocess, "run", fake_run)
    config = SimpleNamespace(
        allowed_verify_commands=None,
        max_changed_files=1,
        protected_paths=[],
    )
    # One rename = one changed file, so the count gate must pass (return None).
    assert protocol_commands._verify_policy_error("exit 0", config, tmp_path) is None


def test_verify_json_refuses_when_changed_file_count_exceeds_policy(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nmax_changed_files = 0\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".looptight.toml"], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=looptight@example.invalid",
            "-c",
            "user.name=looptight",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    (tmp_path / "new_file.py").write_text("# new\n", encoding="utf-8")

    assert main(["verify", "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "max_changed_files" in payload["output"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [("pass", 0), ("fail", 1), ("timeout", 2), ("error", 2)],
)
def test_verify_exit_codes_distinguish_verdict_from_execution_error(status, expected):
    assert _verify_exit_code(status) == expected


def test_verify_exit_code_unknown_status_returns_two():
    assert _verify_exit_code("unknown") == 2


def test_propose_json_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["propose", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert any("fix the timeout" in c["title"] for c in data)
    # compact output, consistent with every other --json command (no indent newlines)
    assert out.strip().count("\n") == 0


def test_propose_rejects_negative_cli_limit():
    with pytest.raises(SystemExit) as exc:
        main(["propose", "--limit", "-1"])

    assert exc.value.code == 2


def test_propose_text_output_groups_by_source_priority(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    # The source and its ranking weight are surfaced so the operator sees why one
    # task outranks another.
    assert "todo" in out
    assert "source priority" in out


@pytest.mark.parametrize("value", ["0", "-1"])
def test_run_rejects_non_positive_max_iterations(value):
    with pytest.raises(SystemExit) as exc:
        main(["run", "goal", "--max-iterations", value])

    assert exc.value.code == 2


def test_run_rejects_negative_patience():
    # --patience must use _non_negative_int, matching verify --patience.
    # A negative value must be caught at parse time (exit 2), not reach RunSpec.
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["run", "--patience", "-1", "goal"])
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["swarm", "--headless", "--worker-timeout", "0"],
        ["swarm", "--headless", "--workers", "0"],
    ],
)
def test_swarm_rejects_non_positive_numeric_options(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 2


def test_propose_shows_clean_summary_not_inline_evidence(tmp_path, monkeypatch, capsys):
    # Status/task-file titles carry their `Evidence:` anchor inline (parsed out for the next
    # directive). propose must show the same clean summary `next` does, not leak "Evidence: ..."
    # into the displayed task name beside the location.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Wire up the export button. Evidence: src/a.py:1; Acceptance: a test covers it.\n",
        encoding="utf-8",
    )
    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if "Wire up the export button" in ln][0]
    assert "Evidence:" not in line  # the inline anchor is not shown as part of the task name
    assert "Wire up the export button ·" in line  # clean summary, then the location separator


def test_propose_candidate_line_separates_title_from_location(tmp_path, monkeypatch, capsys):
    # A candidate's free-form title flows straight into its path with a bare space, leaving the
    # title/location boundary ambiguous. Use the same `·` metadata separator the rest of looptight
    # uses (statusline, swarm tally, status), so the location reads as distinct provenance.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if "fix the timeout" in ln][0]
    assert "· src/a.py:1" in line  # the `·` separator precedes the location


def test_propose_text_output_describes_autonomous_flow(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["propose"]) == 0
    out = capsys.readouterr().out.lower()
    # No human-approval / per-branch framing — the loop is autonomous to main.
    assert "approve" not in out
    assert "branch" not in out
    # The operating agent selects, runs through looptight, verifies, and commits.
    assert "highest-value" in out
    assert "looptight" in out
    assert "verif" in out
    assert "commit" in out
    assert "push" in out


def test_improve_help_has_only_migration_compatibility(capsys):
    try:
        main(["improve", "--headless", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "--headless" in out
    assert "--push" not in out
    assert "--max-iterations" not in out


def test_revert_git_status_oserror_sets_has_tracked_changes(tmp_path, monkeypatch, capsys):
    # commands.py:529 — when subprocess.run for `git status --porcelain` raises
    # OSError, status is set to None and has_tracked_changes becomes True; the
    # command must print the confirmation prompt and return 0 (no crash).
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.is_git_repo", lambda *a, **k: True)

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["git", "status"]:
            raise OSError("git not found")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert main(["revert"]) == 0
    out = capsys.readouterr().out
    assert "--yes" in out or "confirm" in out.lower() or "Re-run" in out


def test_revert_survives_oserror_when_listing_untracked(tmp_path, monkeypatch, capsys):
    # The post-revert `git ls-files` (untracked notice) must not crash the
    # command if git can't be launched for it — the revert already succeeded.
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.is_git_repo", lambda *a, **k: True)

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["git", "ls-files"]:
            raise OSError("git vanished")
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=" M app.py\n")  # dirty
        return subprocess.CompletedProcess(cmd, 0)  # checkout succeeds

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert main(["revert", "--yes"]) == 0
    assert "reverted" in capsys.readouterr().out.lower()


def test_revert_reports_failure_when_git_checkout_fails(tmp_path, monkeypatch, capsys):
    import subprocess

    monkeypatch.chdir(tmp_path)
    # Pretend we're inside a git repo so revert proceeds past the guard.
    monkeypatch.setattr("looptight.commands.is_git_repo", lambda *a, **k: True)

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(args=a[0] if a else [], returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    # A failed checkout must surface a nonzero exit, not a green success message.
    assert main(["revert", "--yes"]) == 1
    out = capsys.readouterr().out.lower()
    assert "reverted" not in out
    assert "failed" in out
    assert "restore not confirmed" in out


def test_revert_reports_failure_when_git_cannot_launch(tmp_path, monkeypatch, capsys):
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.is_git_repo", lambda *a, **k: True)

    def fail_to_launch(*args, **kwargs):
        raise FileNotFoundError("git is not installed")

    monkeypatch.setattr(subprocess, "run", fail_to_launch)

    assert main(["revert", "--yes"]) == 1
    out = capsys.readouterr().out.lower()
    assert "reverted" not in out
    assert "could not run git checkout" in out


def test_revert_notes_untracked_files_left_in_place(tmp_path, monkeypatch, capsys):
    # revert only restores tracked files; it must tell the user that any
    # agent-created untracked files remain, so the leftover state isn't a surprise.
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("orig\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("changed\n")  # tracked change to revert
    (tmp_path / "agent_made_this.py").write_text("new\n")  # untracked

    assert main(["revert", "--yes"]) == 0
    out = capsys.readouterr().out.lower()
    assert "reverted" in out
    assert "untracked" in out


def test_revert_on_clean_tree_reports_nothing_to_revert(tmp_path, monkeypatch, capsys):
    # On a clean tree, revert must not claim it "reverted" anything — there is
    # nothing to revert and the checkout would be a no-op.
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    assert main(["revert", "--yes"]) == 0
    out = capsys.readouterr().out.lower()
    assert "reverted" not in out
    assert "nothing to revert" in out


def test_revert_clean_tree_without_yes_does_not_prompt(tmp_path, monkeypatch, capsys):
    # On a clean tree, plain `revert` (no --yes) must report nothing to revert
    # rather than offer to discard changes that do not exist.
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    assert main(["revert"]) == 0
    out = capsys.readouterr().out
    assert "nothing to revert" in out.lower()
    assert "Re-run with" not in out  # no destructive-confirmation prompt for a clean tree


def test_revert_dirty_tree_without_yes_still_prompts(tmp_path, monkeypatch, capsys):
    # The confirmation gate is preserved when there is real work to discard.
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("changed\n")  # tracked change to discard

    assert main(["revert"]) == 0
    out = capsys.readouterr().out
    assert "Re-run with" in out  # the confirmation gate still fires
    assert (tmp_path / "app.py").read_text() == "changed\n"  # nothing discarded yet


def test_revert_git_calls_set_terminal_prompt_env(tmp_path, monkeypatch, capsys):
    # cmd_revert's git status/checkout/ls-files must pass GIT_TERMINAL_PROMPT=0 so a headless
    # `looptight revert --yes` cannot block on a credential prompt — the uniform headless-safety
    # invariant the other git calls already follow.
    from unittest.mock import patch

    import looptight.commands as cmds

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text("changed\n")  # tracked change → reaches checkout
    (tmp_path / "untracked.txt").write_text("u\n")  # untracked → reaches ls-files

    envs: list = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if list(cmd[:1]) == ["git"] and cmd[1] in ("status", "checkout", "ls-files"):
            envs.append((cmd[1], (kwargs.get("env") or {}).get("GIT_TERMINAL_PROMPT")))
        return real_run(cmd, **kwargs)

    with patch.object(cmds.subprocess, "run", fake_run):
        main(["revert", "--yes"])

    seen = dict(envs)
    assert seen.get("status") == "0" and seen.get("checkout") == "0" and seen.get("ls-files") == "0"


def test_status_json_keeps_v1_keys_and_adds_coordinator_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    v1_keys = {
        "schema_version", "command", "validation", "workspace",
        "claimed_task", "active_claims", "next_action",
    }
    assert v1_keys <= payload.keys()  # v1 status contract preserved
    assert payload["coordinator"]["queued_integrations"] == 0
    assert payload["coordinator"]["queued_tasks"] == 0


def test_migrate_activates_coordinator_and_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    assert main(["migrate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"schema_version": 1, "command": "migrate", "status": "active"}
    assert (tmp_path / ".git" / "looptight" / "coordinator-format.json").is_file()

    assert main(["migrate"]) == 0  # idempotent
    # A no-op re-run says "already active", not the first-run "coordinator active".
    assert "already active" in capsys.readouterr().out.lower()


def test_migrate_refuses_live_legacy_claims(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    claims = tmp_path / ".git" / "looptight" / "claims"
    claims.mkdir(parents=True)
    (claims / "t.json").write_text(
        json.dumps({"schema_version": 1, "task_id": "t", "owner": "o", "claimed_at": 9_999_999_999}),
        encoding="utf-8",
    )

    assert main(["migrate"]) == 2
    assert "legacy" in capsys.readouterr().out
    assert not (tmp_path / ".git" / "looptight" / "coordinator-format.json").exists()


def test_migrate_outside_git_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["migrate"]) == 2
    assert "Git repository" in capsys.readouterr().out


def test_migrate_json_emits_envelope_on_error_paths(tmp_path, monkeypatch, capsys):
    # `migrate --json` must emit a parseable JSON error envelope on its failure paths, not plain
    # text — matching every other --json command. Both not-git and the live-legacy-claim refusal.
    monkeypatch.chdir(tmp_path)
    assert main(["migrate", "--json"]) == 2  # not a git repo
    data = json.loads(capsys.readouterr().out)
    assert data["command"] == "migrate" and data["status"] == "error"
    assert "Git repository" in data["error"] and data["schema_version"] == 1

    subprocess.run(["git", "init", "-q"], check=True)
    claims = tmp_path / ".git" / "looptight" / "claims"
    claims.mkdir(parents=True)
    (claims / "t.json").write_text(
        json.dumps({"schema_version": 1, "task_id": "t", "owner": "o", "claimed_at": 9_999_999_999}),
        encoding="utf-8",
    )
    assert main(["migrate", "--json"]) == 2  # live legacy claim blocks activation
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error" and "legacy" in data["error"]


def test_status_human_output_shows_coordinator_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "coordinator:" in out
    assert "queued" in out and "integrations" in out and "publications" in out


def test_run_and_swarm_parsers_accept_model():
    assert build_parser().parse_args(["run", "--headless", "g", "--model", "opus"]).model == "opus"
    assert build_parser().parse_args(["swarm", "--headless", "--model", "opus"]).model == "opus"


def test_daemon_parser_defaults_and_flags():
    args = build_parser().parse_args(
        [
            "daemon",
            "--headless",
            "--workers",
            "3",
            "--model",
            "opus",
            "--push",
            "--idle-sleep",
            "120",
            "--fault-backoff",
            "10",
            "--max-cycles",
            "5",
        ]
    )
    assert args.headless is True
    assert args.workers == 3
    assert args.model == "opus"
    assert args.push is True
    assert args.idle_sleep == 120.0
    assert args.fault_backoff == 10.0
    assert args.max_cycles == 5
    # sane defaults the operator can rely on
    defaults = build_parser().parse_args(["daemon", "--headless"])
    assert defaults.idle_sleep == 600.0
    assert defaults.fault_max_backoff == 1800.0
    assert defaults.max_cycles == 0
    assert defaults.no_resume_on_limit is False


def test_daemon_requires_headless(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["daemon"]) == 2
    assert "headless" in capsys.readouterr().out.lower()


def test_daemon_dispatches_to_run_daemon(tmp_path, monkeypatch, capsys):
    from looptight.daemon import DaemonReport

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text(
        'agent = "claude"\nverify = "true"\n', encoding="utf-8"
    )

    captured = {}

    def fake_run_daemon(root, **kwargs):
        captured.update(kwargs)
        return DaemonReport(cycles=1, progress=1, idle=0, faults=0, last_reason="ok")

    monkeypatch.setattr("looptight.commands.run_daemon", fake_run_daemon)

    # Pass --agent explicitly: `agent` is not a .looptight.toml key, so relying on
    # config or a claude binary on PATH would make this pass only where claude is
    # installed (it did locally, but not on CI).
    rc = main(
        ["daemon", "--headless", "--agent", "claude", "--workers", "2",
         "--model", "opus", "--push", "--max-cycles", "1"]
    )
    assert rc == 0
    assert captured["workers"] == 2
    assert captured["push"] is True
    assert captured["max_cycles"] == 1
    assert captured["config"].model == "opus"
    assert captured["resume_on_limit"] is True  # on by default for a 24/7 daemon
    out = capsys.readouterr().out
    assert "daemon stopped" in out


def test_doctor_reports_single_machine_coordination(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert main(["doctor"]) != 0  # git repo but no verify command: unsafe to loop
    out = capsys.readouterr().out.lower()
    assert "coordination:" in out
    assert "cross-machine" in out


def test_status_json_includes_coordination_scope(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["coordination_scope"] in ("coordinator", "file-claims", "none")


def test_daemon_parser_accepts_on_fault():
    args = build_parser().parse_args(["daemon", "--headless", "--on-fault", "notify.sh"])
    assert args.on_fault == "notify.sh"
    assert build_parser().parse_args(["daemon", "--headless"]).on_fault is None


def test_daemon_cli_paths_do_not_require_agent_on_path(tmp_path, monkeypatch):
    """CI runners have no claude/codex/opencode installed; providing --agent must
    make the daemon path independent of a PATH binary (regression for ade3e41)."""
    from looptight.daemon import DaemonReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        "looptight.commands.run_daemon",
        lambda root, **kw: DaemonReport(cycles=1, progress=1, idle=0, faults=0, last_reason="ok"),
    )
    # --agent provided: dispatches even with nothing on PATH.
    assert main(["daemon", "--headless", "--agent", "claude", "--verify", "true", "--max-cycles", "1"]) == 0
    # nothing provided and nothing on PATH: clean exit 2, not a crash.
    assert main(["daemon", "--headless", "--verify", "true"]) == 2


def test_next_refuses_outside_a_git_repo(tmp_path, monkeypatch, capsys):
    # `next` must refuse a non-git directory like doctor/status/verify, not treat it as an
    # empty clean queue and emit a generate_ideas directive that drives building into a
    # non-repo. JSON carries a machine-readable not_git error; both forms exit 2.
    monkeypatch.chdir(tmp_path)  # not a git repo

    assert main(["next", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error"
    assert data["error"] == "not_git"
    assert "directive" not in data  # no generate_ideas directive outside a repo

    assert main(["next"]) == 2
    assert "not a git repo" in capsys.readouterr().out.lower()
    assert list(tmp_path.iterdir()) == []  # refused without touching the directory


def test_next_reports_unreadable_coordinator_db_without_traceback(tmp_path, monkeypatch, capsys):
    # A corrupt coordinator.db must not crash every command with a traceback (and must not
    # break the --json contract). It degrades to a clean structured error at exit 2.
    from looptight.coordinator import coordinator_path

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "a.py").write_text("# TODO: fix it\n")
    _commit_fixture()
    path = coordinator_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a sqlite database")

    assert main(["next", "--json"]) == 2
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "error"
    assert data["error"] == "coordinator_unavailable"

    assert main(["next"]) == 2  # human form also clean, no traceback
    assert "coordinator error" in capsys.readouterr().out.lower()


def test_next_human_output_prints_a_generic_error(tmp_path, monkeypatch, capsys):
    # For a non-dirty-worktree error, `next` prints "error: <message>".
    from looptight.tasks import NextResult

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    monkeypatch.setattr(
        "looptight.tasks.next_task",
        lambda *a, **k: NextResult(status="error", error="coordination unavailable"),
    )
    main(["next"])
    out = capsys.readouterr().out
    assert "error:" in out and "coordination unavailable" in out


def test_doctor_next_setup_command_branches():
    from looptight.commands import _doctor_next_setup_command

    assert "init" in _doctor_next_setup_command(None, "claude", True)  # no verify
    assert "Git repository" in _doctor_next_setup_command("pytest", "claude", False)  # no git
    assert "agent CLI" in _doctor_next_setup_command("pytest", None, True)  # no agent
    assert "next" in _doctor_next_setup_command("pytest", "claude", True)  # all ready


def test_revert_in_non_git_dir_reports_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # not a git repo
    assert main(["revert"]) == 1
    assert "not a git repo" in capsys.readouterr().out.lower()


def test_install_skill_command_install_and_already_current(tmp_path, monkeypatch, capsys):
    # Isolate the write to a tmp HOME so the user's real ~/.claude is never touched.
    monkeypatch.setenv("HOME", str(tmp_path))

    assert main(["install-skill"]) == 0
    assert "installed" in capsys.readouterr().out.lower()

    assert main(["install-skill"]) == 0
    assert "already up to date" in capsys.readouterr().out.lower()


def test_hook_command_writes_nonempty_output_to_stdout(tmp_path, monkeypatch, capsys):
    # When run_hook returns a non-empty string (a loop-continuation directive),
    # cmd_hook must write it to stdout so Claude Code can parse the decision.
    # The production branch at commands.py:619 was previously uncovered because
    # the only test used a dormant hook that always returns an empty string.
    import io

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    monkeypatch.setattr("looptight.hook.run_hook", lambda _: ("directive-json", 0))
    assert main(["hook"]) == 0
    assert "directive-json" in capsys.readouterr().out


def test_hook_command_runs_run_hook_and_returns_a_code(tmp_path, monkeypatch, capsys):
    # The hook command reads the Stop-hook event on stdin and returns run_hook's code.
    # With no verify configured the hook is dormant: it allows the stop (exit 0) cleanly.
    import io

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"stop_hook_active": false}'))
    assert main(["hook"]) == 0


def test_statusline_command_falls_back_to_idle_on_error(monkeypatch, capsys):
    # A status line must never break the host editor: if rendering raises, print idle.
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))

    def boom(repo):
        raise RuntimeError("state read blew up")

    monkeypatch.setattr("looptight.commands.read_state", boom)
    assert main(["statusline"]) == 0
    assert "looptight: idle" in capsys.readouterr().out


def test_install_hook_command_install_already_and_uninstall(tmp_path, monkeypatch, capsys):
    # Drive install-hook against the PROJECT settings (cwd/.claude), never the user's real
    # ~/.claude, exercising the install, already-installed, and uninstall output paths.
    monkeypatch.chdir(tmp_path)

    assert main(["install-hook", "--project"]) == 0
    assert "installed" in capsys.readouterr().out.lower()

    assert main(["install-hook", "--project"]) == 0
    assert "already installed" in capsys.readouterr().out.lower()

    assert main(["install-hook", "--project", "--uninstall"]) == 0
    out = capsys.readouterr().out
    assert "1 looptight hook " in out and "hook(s)" not in out  # proper singular, not lazy (s)


def test_install_hook_message_is_scope_accurate(tmp_path, monkeypatch, capsys):
    # A --project install is repo-scoped (fires in THIS repo), not "any repo"; the default user
    # install is global. The guidance line must match the scope it actually wrote.
    monkeypatch.chdir(tmp_path)

    assert main(["install-hook", "--project"]) == 0
    project_out = capsys.readouterr().out.lower()
    assert "this repo" in project_out and "any repo" not in project_out

    # Default (user) install: redirect the path so the real ~/.claude is never touched.
    monkeypatch.setattr("looptight.settings.user_settings_path", lambda: tmp_path / "user-settings.json")
    assert main(["install-hook"]) == 0
    assert "any repo" in capsys.readouterr().out.lower()


def test_install_hook_prints_error_and_returns_1_on_invalid_settings_json(tmp_path, monkeypatch, capsys):
    # commands.py:654 — when install() raises ValueError (e.g. a settings file whose
    # `hooks` key is a list instead of an object), cmd_install_hook must print the error
    # and return exit code 1 rather than crashing or silently succeeding.
    import json

    monkeypatch.chdir(tmp_path)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps({"hooks": []}), encoding="utf-8"
    )

    assert main(["install-hook", "--project"]) == 1
    out = capsys.readouterr().out
    assert "refusing to edit" in out


def test_run_guard_fails_without_agent_or_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\ndirect_main = true\n', encoding="utf-8"
    )

    # No coding agent found → guard fail, exit 2.
    monkeypatch.setattr("looptight.commands.detect_agent", lambda: None)
    code = main(["run", "do it", "--headless"])
    assert code == 2 and "no coding agent" in capsys.readouterr().out.lower()

    # Agent present (via --agent) but no verify configured or detectable → guard fail, exit 2.
    (tmp_path / ".looptight.toml").write_text("direct_main = true\n", encoding="utf-8")
    monkeypatch.setattr("looptight.commands.detect_verify", lambda root: None)
    code = main(["run", "do it", "--headless", "--agent", "claude"])
    assert code == 2 and "verify" in capsys.readouterr().out.lower()


def test_run_reports_not_implemented_from_loop_with_exit_3(tmp_path, monkeypatch, capsys):
    # If the run loop raises NotImplementedError (an unsupported mode), `run` reports it and
    # exits 3 rather than crashing.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\ndirect_main = true\n', encoding="utf-8"
    )

    def raise_not_implemented(*args, **kwargs):
        raise NotImplementedError("this run mode is not supported")

    monkeypatch.setattr("looptight.commands.run_loop", raise_not_implemented)
    code = main(["run", "do the thing", "--headless", "--agent", "claude"])
    assert code == 3
    assert "this run mode is not supported" in capsys.readouterr().out


def test_run_warns_when_native_mode_not_supported(tmp_path, monkeypatch, capsys):
    # When --native is passed but the adapter has no native loop, a yellow warning
    # is printed and the supply loop runs instead (commands.py:204-205).
    from looptight.types import RunResult, StopReason

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(supports_native=False),
    )
    fake_result = RunResult(goal="fix it", agent="codex", mode="supply", stop_reason=StopReason.SUCCESS)
    monkeypatch.setattr("looptight.commands.run_loop", lambda *a, **k: fake_result)

    code = main(["run", "--headless", "--native", "--agent", "codex", "fix it", "--verify", "exit 0"])
    out = capsys.readouterr().out
    assert "no native loop" in out.lower()
    assert code == 0


def test_run_json_reports_not_implemented_error(tmp_path, monkeypatch, capsys):
    # `run --json` must emit a versioned JSON error envelope when run_loop raises
    # NotImplementedError (commands.py:235-237); the human-mode path is already covered.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )

    def raise_not_implemented(*args, **kwargs):
        raise NotImplementedError("unsupported")

    monkeypatch.setattr("looptight.commands.run_loop", raise_not_implemented)
    code = main(["run", "--headless", "--json", "--agent", "codex", "do the thing", "--verify", "exit 0"])
    assert code == 3
    data = json.loads(capsys.readouterr().out)
    assert data["command"] == "run"
    assert "unsupported" in data["error"]


def test_daemon_cli_renders_cycle_outcomes_and_stop_summary(tmp_path, monkeypatch, capsys):
    from looptight.daemon import DaemonCycle, DaemonReport

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    def fake_run_daemon(root, *, on_cycle=None, on_fault=None, **kwargs):
        on_cycle(DaemonCycle(1, "progress", "ok", 2, None, 0.0))
        on_cycle(DaemonCycle(2, "fault", "error", 0, "boom", 30.0))
        if on_fault is not None:
            on_fault({"cycle": 2, "reason": "error", "backoff_s": 30, "last_error": "boom"})
        return DaemonReport(cycles=2, progress=1, idle=0, faults=1, last_reason="error")

    monkeypatch.setattr("looptight.commands.run_daemon", fake_run_daemon)
    code = main([
        "daemon", "--headless", "--agent", "claude", "--verify", "exit 0",
        "--max-cycles", "2", "--on-fault", "true",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "cycle 1" in out and "progress" in out
    assert "cycle 2" in out and "fault" in out and "boom" in out
    assert "daemon stopped" in out and "faults 1" in out


def test_daemon_cli_rejects_too_many_workers_and_missing_verify(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    # More than the worker cap → exit 2.
    code = main(["daemon", "--headless", "--agent", "codex", "--workers", "51"])
    assert code == 2 and "workers must be" in capsys.readouterr().out

    # No verify command configured or detectable → exit 2.
    code = main(["daemon", "--headless", "--agent", "codex"])
    assert code == 2 and "verify" in capsys.readouterr().out.lower()


def test_daemon_cli_on_cycle_detail_empty_branch(tmp_path, monkeypatch, capsys):
    """on_cycle's `else: detail = ""` arm (commands.py:304) fires when merged=0 and not a fault."""
    from looptight.daemon import DaemonCycle, DaemonReport

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    def fake_run_daemon(root, *, on_cycle=None, on_fault=None, **kwargs):
        on_cycle(DaemonCycle(1, "idle", "ok", 0, None, 60.0))
        return DaemonReport(cycles=1, progress=0, idle=1, faults=0, last_reason="ok")

    monkeypatch.setattr("looptight.commands.run_daemon", fake_run_daemon)
    code = main(["daemon", "--headless", "--agent", "claude", "--verify", "exit 0", "--max-cycles", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "cycle 1" in out and "idle" in out
    # The empty-detail arm produces no trailing annotation after the outcome.
    assert "next in 60s" in out


def test_status_watch_parser_accepts_flags():
    args = build_parser().parse_args(["status", "--watch", "--interval", "5"])
    assert args.watch is True and args.interval == 5.0


def test_cmd_status_watch_delegates_to_watch_status(tmp_path, monkeypatch):
    # The three _watch_status tests call it directly and never reach the branch
    # at protocol_commands.py:549 inside cmd_status. Drive it via the CLI so the
    # watch=True arm (lines 549-550) is covered.
    from unittest.mock import MagicMock

    import looptight.protocol_commands as pc

    monkeypatch.chdir(tmp_path)
    called = MagicMock()
    monkeypatch.setattr(pc, "_watch_status", called)
    ret = main(["status", "--watch"])
    assert called.call_count == 1
    assert ret == 0


def test_watch_status_renders_one_tick_without_sleeping(tmp_path, capsys):
    from looptight.console import Console
    from looptight.protocol_commands import _watch_status
    from looptight.ui import write_state

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_state(
        tmp_path,
        {
            "schema_version": 1,
            "manager": {"status": "running"},
            "tasks": [{"id": "t1", "goal": "Fix timeout", "source": "todo", "status": "running"}],
            "workers": [{"number": 1, "task_id": "t1", "status": "running", "error": None}],
        },
    )
    slept: list[float] = []
    ticks = _watch_status(tmp_path, Console(), interval=5.0, sleep=slept.append, max_ticks=1, clear=False)
    assert ticks == 1
    assert slept == []  # a bounded run does not sleep after its final tick
    out = capsys.readouterr().out
    assert "1 running" in out and "#1" in out  # count-status tally, matching the statusline


def test_watch_status_emits_ansi_clear_when_clear_is_true(tmp_path, capsys):
    from looptight.console import Console
    from looptight.protocol_commands import _watch_status
    from looptight.ui import write_state

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_state(
        tmp_path,
        {
            "schema_version": 1,
            "manager": {"status": "running"},
            "tasks": [],
            "workers": [],
        },
    )
    ticks = _watch_status(tmp_path, Console(), interval=5.0, sleep=lambda _: None, max_ticks=1, clear=True)
    assert ticks == 1
    out = capsys.readouterr().out
    assert "\x1b[2J" in out  # clear-screen escape emitted before each tick


def test_watch_status_exits_cleanly_on_keyboard_interrupt(tmp_path):
    from looptight.console import Console
    from looptight.protocol_commands import _watch_status

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    def _raise_ki(_interval):
        raise KeyboardInterrupt

    # max_ticks=0 means unbounded; the injected sleep raises KI after the first tick.
    ticks = _watch_status(tmp_path, Console(), interval=0.0, sleep=_raise_ki, max_ticks=0, clear=False)
    assert ticks == 1


def test_statusline_command_reads_stdin_and_prints_one_line(tmp_path, monkeypatch, capsys):
    import io

    from looptight.ui import write_state

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_state(
        tmp_path,
        {
            "schema_version": 1,
            "manager": {"status": "running"},
            "tasks": [],
            "workers": [{"number": 1, "task_id": "t", "status": "running", "error": None}],
        },
    )
    payload = json.dumps({"workspace": {"current_dir": str(tmp_path)}, "model": {"id": "x"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.splitlines()[0].startswith("looptight:")
    assert "running" in out


def test_statusline_uses_project_dir_when_current_dir_absent(tmp_path, monkeypatch, capsys):
    import io

    from looptight.ui import write_state

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_state(
        tmp_path,
        {
            "schema_version": 1,
            "manager": {"status": "running"},
            "tasks": [],
            "workers": [{"number": 1, "task_id": "t2", "status": "verified", "error": None}],
        },
    )
    payload = json.dumps({"workspace": {"project_dir": str(tmp_path)}, "model": {"id": "x"}})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.splitlines()[0].startswith("looptight:")
    assert "verified" in out


def test_statusline_uses_cwd_key_when_workspace_is_absent(tmp_path, monkeypatch, capsys):
    # commands.py:597: candidate = candidate or data.get("cwd") — third fallback, no workspace key.
    import io

    from looptight.ui import write_state

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    write_state(
        tmp_path,
        {
            "schema_version": 1,
            "manager": {"status": "running"},
            "tasks": [],
            "workers": [{"number": 1, "task_id": "t3", "status": "running", "error": None}],
        },
    )
    payload = json.dumps({"cwd": str(tmp_path)})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.splitlines()[0].startswith("looptight:")
    assert "running" in out


def test_statusline_tolerates_stdin_read_oserror(monkeypatch, capsys):
    # commands.py:587-588: OSError/ValueError from sys.stdin.read() must recover to raw="".
    import types

    fake_stdin = types.SimpleNamespace(isatty=lambda: False, read=lambda: (_ for _ in ()).throw(OSError("broken pipe")))
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("looptight:")


def test_statusline_tolerates_malformed_json_on_stdin(monkeypatch, capsys):
    # commands.py:600-601: invalid JSON on stdin must fall back to cwd without raising.
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("not valid json"))
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("looptight:")


def test_statusline_tolerates_non_dict_json_on_stdin(monkeypatch, capsys):
    # commands.py:593: valid JSON that is not a dict leaves candidate=None and falls back to cwd.
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("[1,2,3]"))
    assert main(["statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("looptight:")


def test_statusline_parser_registered():
    args = build_parser().parse_args(["statusline"])
    assert args.command == "statusline"


def test_propose_source_filter_shows_only_that_source(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix it\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Cover a. Evidence: src/a.py:1; Acceptance: passes.\n", encoding="utf-8"
    )

    assert main(["propose", "--json"]) == 0
    sources = {c["source"] for c in json.loads(capsys.readouterr().out)}
    assert {"todo", "status-next"} <= sources  # both present unfiltered

    assert main(["propose", "--source", "todo", "--json"]) == 0
    filtered = json.loads(capsys.readouterr().out)
    assert filtered and all(c["source"] == "todo" for c in filtered)


def test_status_human_output_shows_idea_quality_line(tmp_path, monkeypatch, capsys):
    # The generated-queue quality also appears in human status, not only --json.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# a\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Harden a. Evidence: src/a.py:1; Acceptance: passes.\n", encoding="utf-8"
    )
    assert main(["status"]) == 0
    out = capsys.readouterr().out.lower()
    assert "idea quality" in out and "groundedness" in out
    assert "1 task " in out and "task(s)" not in out  # proper singular, not the lazy (s)

    # two grounded tasks → proper plural "2 tasks"
    (tmp_path / "src" / "b.py").write_text("# b\n", encoding="utf-8")
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Harden a. Evidence: src/a.py:1; Acceptance: passes.\n"
        "2. Harden b. Evidence: src/b.py:1; Acceptance: passes.\n",
        encoding="utf-8",
    )
    assert main(["status"]) == 0
    assert "2 tasks " in capsys.readouterr().out.lower()


def test_status_names_an_active_goals_vision(tmp_path, monkeypatch, capsys):
    # In goal mode, status should name the vision (like it names a claimed task), not just say
    # "a build goal is active".
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"], check=True
    )
    assert main(["goal", "ship the awwwards landing page"]) == 0
    capsys.readouterr()

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "goal next" in data["next_action"]
    assert "awwwards landing page" in data["next_action"]  # names the vision


def test_propose_source_filter_respects_limit_after_filtering(tmp_path, monkeypatch, capsys):
    # `--source X --limit N` should show up to N of source X, not only the X items that
    # survive the overall top-N ranking cut.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: one\n# TODO: two\n# TODO: three\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(  # curated item outranks todos
        "## Next\n\n1. Curated. Evidence: src/a.py:1; Acceptance: passes.\n", encoding="utf-8"
    )
    assert main(["propose", "--source", "todo", "--limit", "1", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1 and out[0]["source"] == "todo"


def test_status_is_goal_aware(tmp_path, monkeypatch, capsys):
    # With a build goal active, status points at `goal next` and surfaces the goal.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )
    assert main(["goal", "build a CLI todo app"]) == 0
    capsys.readouterr()

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["goal"]["vision"] == "build a CLI todo app"
    assert "goal next" in data["next_action"]

    assert main(["status"]) == 0
    out = capsys.readouterr().out.lower()
    assert "goal: build a cli todo app" in out


def _commit_repo_with_verify(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )


def test_propose_human_output_preserves_bracket_tokens_in_a_title(tmp_path, monkeypatch, capsys):
    # A STATUS.md task title like "Fix the [red] badge" is plausible; its token must not be eaten.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("# x\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "## Next\n\n1. Fix the [red] badge. Evidence: src/x.py:1; Acceptance: passes.\n"
    )
    assert main(["propose"]) == 0
    assert "[red]" in capsys.readouterr().out  # the candidate title's token survives


def test_status_goal_line_preserves_bracket_tokens_in_the_vision(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _commit_repo_with_verify(tmp_path)
    assert main(["goal", "ship the [dim] sections"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "[dim]" in capsys.readouterr().out  # the vision's token survives on the goal line


def test_propose_location_has_no_literal_markup(tmp_path, monkeypatch, capsys):
    # The candidate line is written verbatim (to keep user title tokens), so its location must not
    # carry looptight [dim] markup or it shows literally as "[dim]path[/dim]".
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: handle empty input\n")
    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    assert "[dim]" not in out and "[/dim]" not in out  # no literal markup anywhere in the output
    assert "src/a.py" in out  # the location is still shown (plain)


def test_status_panel_preserves_bracket_tokens_in_a_worker_error(tmp_path, monkeypatch, capsys):
    # The panel is rendered plain text carrying user content; a worker error with a "[red]"-style
    # token must not be silently eaten by markup stripping when status prints the panel.
    from looptight import ui

    monkeypatch.chdir(tmp_path)
    _commit_repo_with_verify(tmp_path)
    ui.write_state(
        tmp_path,
        {
            "schema_version": ui.STATE_SCHEMA_VERSION,
            "manager": {"status": "running"},
            "tasks": [{"id": "t1", "goal": "fix", "status": "failed", "source": "x"}],
            "workers": [{"number": 1, "status": "failed", "task_id": "t1", "error": "tool said [red] then died"}],
            "updated_at": "2026-06-28T00:00:00Z",
        },
    )
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "[red]" in out  # the worker error's bracket-token is preserved, not stripped


def test_status_does_not_repeat_the_next_step_under_two_labels(tmp_path, monkeypatch, capsys):
    # In the dirty/ready states the readiness remediation equals the bottom `next:` action, so
    # status printed the same instruction twice. The `readiness next:` line is suppressed when it
    # would duplicate `next:`.
    monkeypatch.chdir(tmp_path)
    _commit_repo_with_verify(tmp_path)
    (tmp_path / "dirty.txt").write_text("change\n")  # uncommitted → dirty, action == remediation
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    nstep = "review changes and run `looptight verify --json`"
    assert out.count(nstep) == 1, "the next-step instruction is printed twice"
    assert "next: " + nstep in out  # the authoritative next: line is kept
    assert "readiness next: " + nstep not in out  # the duplicate readiness-next line is gone


def test_status_keeps_readiness_next_when_it_differs_from_next(tmp_path, monkeypatch, capsys):
    # A clean repo with no grounded task source has a readiness remediation distinct from the
    # next action, so both lines stay.
    monkeypatch.chdir(tmp_path)
    _commit_repo_with_verify(tmp_path)
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "readiness next:" in out  # a distinct readiness step is still surfaced


def test_status_goal_mode_human_next_drops_the_redundant_building_parenthetical(
    tmp_path, monkeypatch, capsys
):
    # The vision is on the dedicated goal: line, so the human next: line should not repeat it in a
    # (building: …) parenthetical. The JSON next_action keeps naming the vision (tested contract).
    monkeypatch.chdir(tmp_path)
    _commit_repo_with_verify(tmp_path)
    assert main(["goal", "ship the awwwards landing page"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    next_line = next(ln for ln in out.splitlines() if ln.startswith("next:"))
    assert "building:" not in next_line  # the vision is not repeated in the next: line
    assert "ship the awwwards landing page" not in next_line
    assert "goal next" in next_line  # the command is still shown

    assert main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "ship the awwwards landing page" in data["next_action"]  # JSON contract unchanged


def test_status_goal_mode_names_the_vision_once_with_its_verdict(tmp_path, monkeypatch, capsys):
    # Goal-mode static status printed the vision on a dedicated `goal:` line AND again via the
    # overlay panel. The dedicated line is the single source, and it carries the build verdict.
    from looptight import ui

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )
    assert main(["goal", "build a CLI todo app"]) == 0
    ui.write_verdict(tmp_path, "pass")
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    goal_lines = [ln for ln in out.splitlines() if ln.startswith("goal:")]
    assert len(goal_lines) == 1, f"vision duplicated across goal lines: {goal_lines}"
    assert "verify: pass" in goal_lines[0]  # build health on the dedicated goal line


def test_status_goal_line_shows_max_iterations_like_goal_status(tmp_path, monkeypatch, capsys):
    # The `status` goal line and `goal status` describe the same goal; both must show the
    # max-iterations backstop. Previously `status` dropped it, so "max 5" appeared under
    # `goal status` but vanished under `status` for the same goal.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "true"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=tmp_path, check=True,
    )
    assert main(["goal", "build a CLI todo app", "--max-iterations", "5"]) == 0
    capsys.readouterr()

    assert main(["status"]) == 0
    status_line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("goal:")][0]
    assert "max 5" in status_line

    assert main(["goal", "status"]) == 0
    goal_status_line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("goal:")][0]
    assert "max 5" in goal_status_line  # the two descriptors agree


def test_positive_int_rejects_zero_and_port_rejects_out_of_range():
    # The argparse type validators reject invalid values with ArgumentTypeError,
    # so a bad --port or count fails at parse time rather than deep in a command.
    from looptight.cli import _positive_int, _port

    assert _positive_int("3") == 3
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("-1")

    assert _port("8765") == 8765
    assert _port("0") == 0
    with pytest.raises(argparse.ArgumentTypeError):
        _port("65536")


def test_non_negative_int_and_positive_float_validators():
    from looptight.cli import _non_negative_int, _positive_float

    assert _non_negative_int("0") == 0
    assert _non_negative_int("5") == 5
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_int("-1")

    assert _positive_float("1.5") == 1.5
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_float("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_float("-0.1")


def test_positive_int_and_non_negative_int_reject_non_numeric():
    from looptight.cli import _non_negative_int, _positive_int

    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("abc")
    with pytest.raises(argparse.ArgumentTypeError):
        _non_negative_int("xyz")


def test_positive_float_rejects_non_numeric():
    # _positive_float must raise ArgumentTypeError (not ValueError) for non-numeric
    # input, consistent with the sibling _positive_int / _non_negative_int validators.
    from looptight.cli import _positive_float

    with pytest.raises(argparse.ArgumentTypeError):
        _positive_float("abc")


def test_run_json_emits_versioned_result_with_escalation_key(tmp_path, monkeypatch, capsys):
    # `run --json` is machine-readable: a versioned RunResult with an `escalation`
    # key (null on a clean SUCCESS) and per-iteration objects that carry no output.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".looptight.toml").write_text("direct_main = true\n")
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda *args: adapter)

    assert main(["run", "--headless", "fix it", "--agent", "codex", "--verify", "true", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)  # single JSON object, no human banner on stdout
    assert data["command"] == "run"
    assert data["schema_version"] == 1
    assert data["stop_reason"] == "success"
    assert data["escalation"] is None
    assert "output" not in data["iterations"][0]  # per-iteration stays bounded


def test_run_json_guard_failure_emits_json_not_markup(tmp_path, monkeypatch, capsys):
    # A config-guard failure under --json must still honor the JSON contract: a
    # single JSON error object, not Rich markup, on stdout.
    monkeypatch.chdir(tmp_path)
    assert main(["run", "fix it", "--json"]) == 2  # no --headless -> guard fails
    out = capsys.readouterr().out
    data = json.loads(out)  # parses as one JSON object, not "[red]...[/red]"
    assert data["command"] == "run"
    assert data["schema_version"] == 1
    assert isinstance(data["error"], str) and data["error"]
    assert "[red]" not in out


def test_verify_patience_surfaces_session_native_stall(tmp_path, monkeypatch, capsys):
    # verify --patience persists the trajectory across calls and escalates a stuck
    # sequence; a passing verify resets it. A stuck verify command is one that fails
    # with the same output every time.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    stuck = 'python -c "import sys; sys.stderr.write(chr(10).join([\'FAILED t::x - boom\',\'1 failed\'])); sys.exit(1)"'

    def run(extra):
        assert main(["verify", "--verify", stuck, "--patience", "2", "--json"]) == 1
        return json.loads(capsys.readouterr().out)

    first = run(None)
    assert first["stall"]["decision"] == "continue"  # not enough history yet
    assert "escalation" not in first["stall"]  # additive: present only when stalled
    run(None)
    third = run(None)
    assert third["stall"]["decision"] == "escalate"  # never improved across 3 tries
    assert third["stall"]["escalation"]["kind"] == "escalated"
    assert any("t::x" in f for f in third["stall"]["escalation"]["failures"])

    # A passing verify clears the attempt: no stall on the next failing run's first call.
    assert main(["verify", "--verify", "true", "--patience", "2", "--json"]) == 0
    cleared = json.loads(capsys.readouterr().out)
    assert "stall" not in cleared or cleared["stall"] is None  # pass -> no stall


def test_verify_human_next_step_reflects_a_stall(tmp_path, monkeypatch, capsys):
    # On a stall, the human `next:` line must not be the generic "continue fixing":
    # the stall says the current approach is not progressing, so it should point at
    # a different approach / human review.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    stuck = 'python -c "import sys; sys.stderr.write(chr(10).join([\'FAILED t::x - boom\',\'1 failed\'])); sys.exit(1)"'

    def run():
        assert main(["verify", "--verify", stuck, "--patience", "2"]) == 1
        return capsys.readouterr().out

    run()
    run()
    out = run()  # third attempt: stalled
    assert "stalled:" in out
    assert "continue fixing, then rerun" not in out  # not the generic advice
    assert "different approach" in out or "human" in out.lower()


def test_verify_json_without_patience_has_no_stall_key(tmp_path, monkeypatch, capsys):
    # The default verify --json contract is unchanged: no stall key.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert main(["verify", "--verify", "true", "--json"]) == 0
    assert "stall" not in json.loads(capsys.readouterr().out)


def test_stall_signal_returns_none_when_patience_is_zero(tmp_path):
    # protocol_commands.py:116 — patience <= 0 returns None immediately without
    # touching the trajectory or importing metacog; guards the early-return guard.
    import looptight.protocol_commands as pc

    result = pc._stall_signal(tmp_path, "true", object(), patience=0)
    assert result is None

    result = pc._stall_signal(tmp_path, "true", object(), patience=-1)
    assert result is None


def test_verify_human_stall_without_escalation_prints_continue_fixing(tmp_path, monkeypatch, capsys):
    # protocol_commands.py:86 — the else branch: a stall whose dict has no "escalation" key
    # should print the generic "continue fixing" message, not the stall-specific one.
    # A mutation widening the elif guard to `if stall:` would silence the stall message
    # and print the escalation summary, which no test previously caught in human mode.
    import looptight.protocol_commands as pc
    from looptight.types import VerifyResult

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    failing = VerifyResult(passed=False, exit_code=1, output="1 failed")
    monkeypatch.setattr(pc, "run_verify", lambda *a, **kw: failing)
    monkeypatch.setattr(pc, "_stall_signal", lambda *a, **kw: {"reason": "STOP_NO_PROGRESS"})

    assert main(["verify", "--verify", "false"]) == 1
    out = capsys.readouterr().out
    assert "continue fixing, then rerun" in out
    assert "different approach" not in out  # escalation message must not appear


def test_stall_signal_returns_none_on_passing_result(tmp_path):
    # protocol_commands.py:132 — a passing verify result returns None immediately
    # after recording (trajectory clears its file on pass). A regression removing
    # this guard would cause stall logic to run on every pass.
    import types

    import looptight.protocol_commands as pc

    passing = types.SimpleNamespace(passed=True, output="")
    assert pc._stall_signal(tmp_path, "pytest", passing, patience=3) is None


def test_stall_signal_returns_none_when_no_trajectory_entries(tmp_path):
    # protocol_commands.py:132 — when trajectory.record returns [] (e.g. outside a
    # git repo), the stall logic has nothing to assess and must return None rather
    # than crashing on an empty history.
    import types

    import looptight.protocol_commands as pc

    # tmp_path is not a git worktree, so trajectory.record returns []
    failing = types.SimpleNamespace(passed=False, output="some failure output", score=None)
    assert pc._stall_signal(tmp_path, "pytest", failing, patience=3) is None


def test_verify_json_stop_no_progress_has_no_escalation_key(tmp_path, monkeypatch, capsys):
    # _stall_signal's STOP_NO_PROGRESS branch (protocol_commands.py:137-145): a
    # "improved then plateaued" verdict emits decision="stop_no_progress" with no
    # escalation key — the agent should stop but a human review is not requested.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    from looptight.metacog import Decision

    monkeypatch.setattr("looptight.metacog.assess", lambda history, patience: Decision.STOP_NO_PROGRESS)
    failing_cmd = 'python -c "import sys; sys.exit(1)"'
    assert main(["verify", "--verify", failing_cmd, "--patience", "2", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["stall"]["decision"] == "stop_no_progress"
    assert "escalation" not in out["stall"]


def test_task_source_health_counts_discoverable_signals(tmp_path):
    # Auto-discovered TODOs/skips are looptight's primary task source. A repo with
    # discoverable work is a healthy task source, even without a configured tasks
    # file or docs/STATUS.md — otherwise readiness wrongly says "add grounded tasks"
    # to a repo that already has them.
    from looptight.protocol_commands import _task_source_health

    (tmp_path / "app").mkdir()
    assert _task_source_health(tmp_path, ()) == "missing"  # nothing discoverable yet

    (tmp_path / "app" / "core.py").write_text("# TODO: handle empty input\n", encoding="utf-8")
    assert _task_source_health(tmp_path, ()) == "configured"  # a real discoverable TODO


def test_task_source_health_recognizes_status_md_without_config_tasks(tmp_path):
    # When config_tasks is empty but docs/STATUS.md exists the function must return
    # "configured" via the STATUS.md branch (protocol_commands.py:822), not via
    # TODO-discovery — so a looptight-managed repo with an empty TODO scan is still
    # recognized as healthy. The existing test covers only the TODO-discovery branch.
    from looptight.protocol_commands import _task_source_health

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("## Next\n\n_No work._\n", encoding="utf-8")
    assert _task_source_health(tmp_path, ()) == "configured"


def test_task_source_health_recognizes_skipped_tests_without_todos(tmp_path):
    # `from_skipped_tests` is the second operand of the `or` in _task_source_health
    # (protocol_commands.py:828). The existing test always hits `from_todos()` first,
    # so dropping skip-discovery entirely would be undetected. This test ensures a repo
    # with only a skipped test (and no TODO) still reports "configured".
    from looptight.protocol_commands import _task_source_health

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text(
        "import pytest\n\ndef test_stub():\n    pytest.skip('not implemented')\n",
        encoding="utf-8",
    )
    assert _task_source_health(tmp_path, ()) == "configured"


def test_task_source_health_returns_configured_for_nonempty_config_tasks(tmp_path):
    # The `if config_tasks: return "configured"` early-exit at protocol_commands.py:823
    # is never reached by the other three tests (all pass `()`), so a regression
    # removing it would be undetected.
    from looptight.protocol_commands import _task_source_health

    assert _task_source_health(tmp_path, ("TODO.md",)) == "configured"


def test_propose_source_filter_empty_is_not_clean_tree(tmp_path, monkeypatch, capsys):
    # `propose --source lint` with no lint candidates but real todo candidates must
    # not claim a "clean tree" — that misleads the user into thinking there is no work.
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "m.py").write_text("# TODO: real work here\n", encoding="utf-8")

    assert main(["propose", "--source", "lint"]) == 0
    out = capsys.readouterr().out
    assert "clean tree" not in out  # the tree is not clean; there is a todo
    assert "lint" in out  # names the empty source
    # The unfiltered query still surfaces the todo.
    assert main(["propose"]) == 0
    assert "real work here" in capsys.readouterr().out


def test_propose_no_signals_does_not_claim_clean_tree(tmp_path, monkeypatch, capsys):
    # The no-candidates message speaks to task signals, not git state, so it must not assert
    # "(clean tree)" when the worktree has untracked files (revert reports them in place).
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / "notes.txt").write_text("just some notes, no task markers\n", encoding="utf-8")

    assert main(["propose"]) == 0
    out = capsys.readouterr().out
    assert "No candidate tasks found from repo signals" in out  # guidance still prints
    assert "clean tree" not in out  # the tree is not clean


def test_changed_entries_sets_terminal_prompt_env(tmp_path):
    # _changed_entries' `git status --short` (the looptight status path) must pass
    # GIT_TERMINAL_PROMPT=0 so a headless run can't block on a credential prompt.
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(pc.subprocess, "run", fake_run):
        pc._changed_entries(tmp_path)
    assert captured.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


def test_git_common_dir_sets_terminal_prompt_env(tmp_path):
    # _git_common_dir's `git rev-parse` must likewise be non-interactive.
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    with patch.object(pc.subprocess, "run", fake_run):
        pc._git_common_dir(tmp_path)
    assert captured.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


def test_coordinator_activation_returns_unknown_when_git_common_dir_fails(tmp_path, monkeypatch):
    # protocol_commands.py:797-798 — when the workspace is not "not_git" but
    # _git_common_dir returns None (e.g. git subprocess error), the result must
    # be "unknown" so callers can distinguish this from a healthy "active" store.
    import looptight.protocol_commands as pc

    monkeypatch.setattr(pc, "_git_common_dir", lambda _path: None)
    result = pc._coordinator_activation(tmp_path, "clean")
    assert result == "unknown"


def test_coordinator_activation_not_git_and_active_branches(tmp_path, monkeypatch):
    import looptight.protocol_commands as pc

    # not_git branch: workspace=="not_git" returns immediately without calling git
    result = pc._coordinator_activation(tmp_path, "not_git")
    assert result == "not_git"

    # active branch: workspace is not "not_git" and _git_common_dir returns a path
    monkeypatch.setattr(pc, "_git_common_dir", lambda _path: tmp_path / ".git")
    result = pc._coordinator_activation(tmp_path, "clean")
    assert result == "active"


def test_cmd_status_git_sets_terminal_prompt_env(tmp_path, monkeypatch, capsys):
    # cmd_status's `git status --porcelain` must pass GIT_TERMINAL_PROMPT=0 so
    # `looptight status` cannot block on a credential prompt in a headless session.
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    captured_calls: list = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if list(cmd[:3]) == ["git", "status", "--porcelain"]:
            captured_calls.append(kwargs.get("env"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    with patch.object(pc.subprocess, "run", fake_run):
        main(["status"])

    assert captured_calls, "cmd_status did not call `git status --porcelain`"
    assert all(
        env is not None and env.get("GIT_TERMINAL_PROMPT") == "0"
        for env in captured_calls
    )


def test_cmd_doctor_git_sets_terminal_prompt_env(tmp_path, monkeypatch, capsys):
    # cmd_doctor's `git status --porcelain` must pass GIT_TERMINAL_PROMPT=0 so
    # `looptight doctor` cannot block on a credential prompt in a headless session.
    from unittest.mock import patch

    import looptight.commands as cmd_module

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    captured_calls: list = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if list(cmd[:3]) == ["git", "status", "--porcelain"]:
            captured_calls.append(kwargs.get("env"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kwargs)

    with patch.object(cmd_module.subprocess, "run", fake_run):
        main(["doctor"])

    assert captured_calls, "cmd_doctor did not call `git status --porcelain`"
    assert all(
        env is not None and env.get("GIT_TERMINAL_PROMPT") == "0"
        for env in captured_calls
    )


def test_doctor_git_oserror_reports_not_git(tmp_path, monkeypatch, capsys):
    # cmd_doctor's subprocess.run call for `git status --porcelain` can raise OSError
    # when git is not on PATH or the OS refuses the exec. The except OSError clause at
    # commands.py:397-398 sets git=None so workspace becomes "not_git"; this was previously
    # uncovered because tmp_path outside git returns a non-zero returncode, not an OSError.
    from unittest.mock import patch

    import looptight.commands as cmd_module

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if list(cmd[:3]) == ["git", "status", "--porcelain"]:
            raise OSError("git not found")
        return real_run(cmd, **kwargs)

    with patch.object(cmd_module.subprocess, "run", fake_run):
        exit_code = main(["doctor", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert exit_code == 1  # OSError → workspace not_git → unsafe → exit 1
    assert data.get("readiness", {}).get("checks", {}).get("git") == "not_git"


def test_cmd_status_git_oserror_reports_not_git(tmp_path, monkeypatch, capsys):
    # cmd_status's subprocess.run for `git status --porcelain` can raise OSError when
    # git is not on PATH or the OS refuses the exec. The except OSError at
    # protocol_commands.py:560-561 sets git=None so workspace becomes "not_git";
    # this was previously uncovered because tmp_path outside git returns a non-zero
    # returncode (not an OSError). Parallel to test_doctor_git_oserror_reports_not_git.
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "exit 0"\n', encoding="utf-8")

    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if list(cmd[:3]) == ["git", "status", "--porcelain"]:
            raise OSError("git not found")
        return real_run(cmd, **kwargs)

    with patch.object(pc.subprocess, "run", fake_run):
        exit_code = main(["status", "--json"])

    data = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert data.get("workspace") == "not_git"


# ── _active_task_identity coverage ───────────────────────────────────────────


def _make_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, check=True, capture_output=True)
    (path / "a.py").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True, capture_output=True)


def test_active_task_identity_returns_idea_id_for_active_lease(tmp_path):
    # lines 99, 106-108: a claimed task with idea_id → returns that string
    from looptight.claims import owner_id
    from looptight.coordinator import Coordinator
    from looptight.protocol_commands import _active_task_identity

    _make_git_repo(tmp_path)
    coordinator = Coordinator.open(tmp_path)
    assert coordinator is not None
    owner = owner_id(tmp_path)
    run = coordinator.start_run("session", owner=owner)
    coordinator.claim(
        [{"id": "t1", "idea_id": "abc123xyz", "evidence": "Evidence: a.py:1", "goal": "fix it"}],
        run.id, ttl_s=60,
    )
    coordinator.close()

    result = _active_task_identity(tmp_path)
    assert result == "abc123xyz"


def test_active_task_identity_returns_none_when_no_lease(tmp_path):
    # lines 104-105: no active lease → None
    from looptight.protocol_commands import _active_task_identity

    _make_git_repo(tmp_path)
    assert _active_task_identity(tmp_path) is None


def test_active_task_identity_returns_none_outside_git(tmp_path):
    # line 99: Coordinator.open returns None outside git → None
    from looptight.protocol_commands import _active_task_identity

    non_git = tmp_path / "notgit"
    non_git.mkdir()
    assert _active_task_identity(non_git) is None


def test_active_task_identity_swallows_exception(tmp_path, monkeypatch):
    # lines 107-108: any exception is swallowed, returns None
    import looptight.coordinator as _coord
    from looptight.protocol_commands import _active_task_identity

    _make_git_repo(tmp_path)
    monkeypatch.setattr(
        _coord.Coordinator,
        "open",
        staticmethod(lambda p: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    assert _active_task_identity(tmp_path) is None


def test_active_task_identity_returns_none_when_idea_id_absent(tmp_path):
    # line 106: lease payload with no idea_id key → str("") or None → None
    from looptight.claims import owner_id
    from looptight.coordinator import Coordinator
    from looptight.protocol_commands import _active_task_identity

    _make_git_repo(tmp_path)
    coordinator = Coordinator.open(tmp_path)
    assert coordinator is not None
    owner = owner_id(tmp_path)
    run = coordinator.start_run("session", owner=owner)
    coordinator.claim(
        [{"id": "t2", "evidence": "Evidence: a.py:1", "goal": "no identity"}],
        run.id, ttl_s=60,
    )
    coordinator.close()

    assert _active_task_identity(tmp_path) is None


def test_humanize_status_passes_non_string_values_through():
    from looptight.protocol_commands import humanize_status

    assert humanize_status(42) == 42
    assert humanize_status(None) is None
    assert humanize_status(True) is True


def test_humanized_checks_joins_tokens_and_rewrites_not_git():
    # humanized_checks (protocol_commands.py:529) has no direct unit test;
    # only humanize_status alone is covered, leaving the ` · `-join and the
    # not_git rewrite unguarded against regression.
    from looptight.protocol_commands import humanized_checks

    result = humanized_checks({"git": "not_git", "verify": "configured"})
    assert result == "git not a git repo · verify configured"


def test_goal_descriptor_covers_all_branch_combinations():
    # goal_descriptor (protocol_commands.py:534) has no unit test; its `continuous`
    # and `max_iterations` suffixes could be removed without any existing test failing.
    import types
    from looptight.protocol_commands import goal_descriptor

    def _g(continuous, max_iterations):
        return types.SimpleNamespace(
            vision="ship it", iteration=3, continuous=continuous, max_iterations=max_iterations
        )

    assert goal_descriptor(_g(False, 0)) == "goal: ship it (iteration 3)"
    assert goal_descriptor(_g(True, 0)) == "goal: ship it (iteration 3, continuous)"
    assert goal_descriptor(_g(False, 10)) == "goal: ship it (iteration 3, max 10)"
    assert goal_descriptor(_g(True, 10)) == "goal: ship it (iteration 3, continuous, max 10)"


def test_verify_continues_despite_write_verdict_failure(tmp_path, monkeypatch, capsys):
    # protocol_commands.py:57 swallows write_verdict errors so UI bookkeeping never
    # breaks verify. This test confirms a crashing write_verdict doesn't hide a pass.
    import looptight.ui as _ui

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_ui, "write_verdict", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    rc = main(["verify", "--json", "--verify", "exit 0"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "pass"


def test_changed_entries_returns_none_on_oserror(tmp_path, monkeypatch):
    # protocol_commands.py:380 — _changed_entries' subprocess.run must catch OSError
    # so `looptight verify` degrades gracefully when git is absent from PATH instead
    # of crashing with a FileNotFoundError traceback (all sibling git calls do catch it).
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    with patch.object(pc.subprocess, "run", side_effect=OSError("git not found")):
        result = pc._changed_entries(tmp_path)

    assert result is None


def test_changed_entries_returns_none_on_nonzero_returncode(tmp_path, monkeypatch):
    # protocol_commands.py:391 — _changed_entries' nonzero-returncode branch was not
    # directly tested; a mutation dropping the `if result.returncode != 0` guard would
    # return an empty list instead of None, silently bypassing the caller's None check.
    from subprocess import CompletedProcess
    from unittest.mock import patch

    import looptight.protocol_commands as pc

    fake = CompletedProcess(args=[], returncode=128, stdout="", stderr="")
    with patch.object(pc.subprocess, "run", return_value=fake):
        result = pc._changed_entries(tmp_path)

    assert result is None


def test_count_non_int_value_returns_zero():
    # protocol_commands.py:945 — the `else 0` branch when a counts dict has a non-int
    # value (e.g. from future schema evolution) was never directly tested; a regression
    # dropping the isinstance guard would silently pass the raw value to status JSON.
    from looptight.protocol_commands import _count

    assert _count({"k": "oops"}, "k") == 0
    assert _count({"k": 5}, "k") == 5
    assert _count(None, "k") == 0


def test_concurrency_remediation_priority_branches():
    # protocol_commands.py:948 — _concurrency_remediation has four guard-and-return
    # branches; all lack a direct test so any can be deleted without failing the suite.
    from looptight.protocol_commands import _concurrency_remediation

    assert _concurrency_remediation("not_git", False, "safe") == "run inside a Git repository"
    assert _concurrency_remediation("clean", True, "unsafe") == "wait for legacy claims to expire or clear them, then run `looptight migrate`"
    assert _concurrency_remediation("clean", False, "degraded") == "wait for active coordinator work to drain"
    assert _concurrency_remediation("clean", False, "safe") == "none"


def test_ensure_pycache_ignored_writes_gitignore_when_absent(tmp_path):
    # commands.py:66 — when no .gitignore exists, _ensure_pycache_ignored must write
    # one containing __pycache__/ so a Python verify run doesn't dirty the worktree.
    from looptight.commands import _ensure_pycache_ignored
    from looptight.console import Console
    import io

    out = io.StringIO()
    _ensure_pycache_ignored(tmp_path, Console(file=out))
    gitignore = tmp_path / ".gitignore"
    assert gitignore.is_file(), ".gitignore was not created"
    assert "__pycache__/" in gitignore.read_text(encoding="utf-8")
    assert "wrote" in out.getvalue()


def test_ensure_pycache_ignored_leaves_existing_gitignore_untouched(tmp_path):
    # commands.py:75 — when a .gitignore already exists, _ensure_pycache_ignored must
    # return without writing or overwriting it, preserving the user's configuration.
    from looptight.commands import _ensure_pycache_ignored
    from looptight.console import Console
    import io

    original = "*.pyc\n"
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(original, encoding="utf-8")
    out = io.StringIO()
    _ensure_pycache_ignored(tmp_path, Console(file=out))
    assert gitignore.read_text(encoding="utf-8") == original, ".gitignore was modified"
    assert out.getvalue() == "", "unexpected console output when .gitignore already exists"


def test_doctor_coordinator_state_active_and_not_git(tmp_path):
    # commands.py:492 — _doctor_coordinator_state returns "active" when git is
    # ready and "not a git repo" when it is not; test both branches directly.
    from looptight.commands import _doctor_coordinator_state

    assert _doctor_coordinator_state(tmp_path, True) == "active"
    assert _doctor_coordinator_state(tmp_path, False) == "not a git repo"


def test_coordination_line_none_scope_returns_label_only(tmp_path, monkeypatch):
    # commands.py:483 — when coordination_scope returns "none", _coordination_line
    # must return just the label with no suffix appended.
    from looptight import commands
    from looptight.commands import _coordination_line

    monkeypatch.setattr(commands, "coordination_scope", lambda _: "none")
    result = _coordination_line(tmp_path)
    assert result == "not a git repo"
    assert "cross-machine" not in result


def test_coordination_line_coordinator_scope_appends_suffix(tmp_path, monkeypatch):
    # commands.py:483 — when coordination_scope returns a non-"none" value,
    # _coordination_line must append the cross-machine-unsupported suffix.
    from looptight import commands
    from looptight.commands import _coordination_line

    monkeypatch.setattr(commands, "coordination_scope", lambda _: "coordinator")
    result = _coordination_line(tmp_path)
    assert "cross-machine sharing is unsupported" in result


def test_coordination_line_file_claims_scope_appends_suffix(tmp_path, monkeypatch):
    # commands.py:476 — _COORDINATION_LABELS["file-claims"] maps to the same label as
    # "coordinator"; the branch must return the cross-machine suffix, not an old
    # "legacy file claims" label.  A mutation of the dict value would otherwise go
    # undetected because neither of the two prior tests covers this key.
    from looptight import commands
    from looptight.commands import _coordination_line

    monkeypatch.setattr(commands, "coordination_scope", lambda _: "file-claims")
    result = _coordination_line(tmp_path)
    assert "local-only (SQLite coordinator)" in result
    assert "cross-machine sharing is unsupported" in result


def test_unquote_git_path_strips_quotes_and_leaves_plain_paths():
    # protocol_commands.py:415 — git wraps paths containing special characters in
    # double-quotes; _unquote_git_path must strip exactly those quotes and leave
    # already-unquoted paths unchanged.
    from looptight.protocol_commands import _unquote_git_path

    assert _unquote_git_path('"path with spaces"') == "path with spaces"
    assert _unquote_git_path("plain/path") == "plain/path"


def test_status_reads_legacy_claims_when_coordinator_absent(tmp_path, monkeypatch, capsys):
    # protocol_commands.py:593-595: the else branch runs when Coordinator.open returns None
    # and claim_dir returns a path — exercises ClaimStore.summary on the legacy file path.
    import looptight.protocol_commands as pc
    from looptight.claims import ClaimStore

    monkeypatch.chdir(tmp_path)

    # Prepare a claim directory (no coordinator marker, so _fail_closed_if_migrated is silent)
    claim_store_dir = tmp_path / "looptight" / "claims"
    claim_store_dir.mkdir(parents=True)

    # No coordinator — forces the else branch
    monkeypatch.setattr(pc.Coordinator, "open", staticmethod(lambda p: None))

    # claim_dir returns the prepared directory
    monkeypatch.setattr(pc, "claim_dir", lambda p: claim_store_dir)

    # Spy: track ClaimStore.summary calls
    summary_calls: list = []
    real_summary = ClaimStore.summary

    def _spy(self):
        summary_calls.append(True)
        return real_summary(self)

    monkeypatch.setattr(ClaimStore, "summary", _spy)

    assert main(["status"]) == 0
    assert summary_calls, "ClaimStore.summary was not called on the legacy path"


def test_daemon_cli_interruptible_sleep_executes_and_returns(tmp_path, monkeypatch):
    # commands.py:290-295 — interruptible_sleep is passed to run_daemon as the `sleep`
    # kwarg but no existing test has fake_run_daemon call it. This test drives the
    # function through a zero-remaining-time path so every line executes without blocking.
    from looptight.daemon import DaemonReport
    import looptight.commands as cmd_mod

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    sleep_calls: list[float] = []
    monkeypatch.setattr(cmd_mod.time, "sleep", lambda s: sleep_calls.append(s))

    def fake_run_daemon(root, *, sleep=None, **kwargs):
        # Call with a tiny positive duration so line 295 (time.sleep) is reached
        # on the first iteration, then the deadline passes and the loop exits.
        if sleep is not None:
            sleep(0.001)
        return DaemonReport(cycles=1, progress=0, idle=1, faults=0, last_reason="ok")

    monkeypatch.setattr(cmd_mod, "run_daemon", fake_run_daemon)

    code = main([
        "daemon", "--headless", "--agent", "claude", "--verify", "exit 0", "--max-cycles", "1",
    ])
    assert code == 0
    # time.sleep was called once (line 295) because the 0.001s budget wasn't exhausted yet.
    assert sleep_calls, "interruptible_sleep must call time.sleep when deadline is in the future"


def test_daemon_cli_fault_hook_subprocess_exception_is_swallowed(tmp_path, monkeypatch, capsys):
    # commands.py:327-328 — when the --on-fault subprocess.run call raises (e.g.
    # TimeoutExpired or OSError), the `except Exception: pass` guard must swallow
    # it so a broken notification hook never crashes the daemon.
    from looptight.daemon import DaemonReport
    import looptight.commands as cmd_mod

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    def fake_run_daemon(root, *, on_fault=None, on_cycle=None, **kwargs):
        # Trigger the fault hook so commands.py:327 is exercised.
        if on_fault is not None:
            on_fault({"cycle": 1, "reason": "error", "backoff_s": 5, "last_error": "boom"})
        return DaemonReport(cycles=1, progress=0, idle=0, faults=1, last_reason="error")

    monkeypatch.setattr(cmd_mod, "run_daemon", fake_run_daemon)
    # Make subprocess.run raise OSError — this exercises the except handler.
    monkeypatch.setattr(cmd_mod.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(OSError("hook failed")))

    code = main([
        "daemon", "--headless", "--agent", "claude", "--verify", "exit 0",
        "--max-cycles", "1", "--on-fault", "hook.sh",
    ])
    # The OSError from the hook must be swallowed; daemon must exit cleanly.
    assert code == 0


def test_daemon_cli_request_stop_prints_message_only_once(tmp_path, monkeypatch, capsys):
    # commands.py:283-285 — the `request_stop` handler prints the shutdown message
    # only on the first call (guarded by `if not stop["flag"]`).  Invoking it twice
    # must produce exactly one message, and the flag must be set so the daemon stops.
    from looptight.daemon import DaemonReport
    import looptight.commands as cmd_mod

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    captured_handler: list = []

    def capturing_signal(signum, handler):
        if callable(handler):
            captured_handler.append(handler)
        return signal.SIG_DFL

    import signal
    monkeypatch.setattr(cmd_mod.signal, "signal", capturing_signal)

    def fake_run_daemon(root, **kwargs):
        # Invoke the handler twice; only the first call should print.
        for h in captured_handler:
            h(2, None)
            h(2, None)
        return DaemonReport(cycles=1, progress=0, idle=1, faults=0, last_reason="ok")

    monkeypatch.setattr(cmd_mod, "run_daemon", fake_run_daemon)
    code = main(["daemon", "--headless", "--agent", "claude", "--verify", "exit 0", "--max-cycles", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("shutdown requested") == 1


def test_daemon_cli_signal_registration_error_is_ignored(tmp_path, monkeypatch, capsys):
    # commands.py:334-335 — when signal.signal raises ValueError (e.g. called from a
    # non-main thread) or OSError (signal unsupported), the exception is caught and
    # the daemon proceeds normally without crashing.
    from looptight.daemon import DaemonReport
    import looptight.commands as cmd_mod

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    def raising_signal(signum, handler):
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(cmd_mod.signal, "signal", raising_signal)

    def fake_run_daemon(root, **kwargs):
        return DaemonReport(cycles=1, progress=0, idle=1, faults=0, last_reason="ok")

    monkeypatch.setattr(cmd_mod, "run_daemon", fake_run_daemon)
    code = main(["daemon", "--headless", "--agent", "claude", "--verify", "exit 0", "--max-cycles", "1"])
    assert code == 0


def test_python_m_looptight_help_exits_zero():
    # __main__.py:5 — `python -m looptight --help` must exit 0 so the entry point
    # is reachable and the standard help contract holds.
    result = subprocess.run(
        ["python", "-m", "looptight", "--help"],
        capture_output=True,
    )
    assert result.returncode == 0


def test_main_module_if_name_block_is_covered():
    # __main__.py:5 — the `if __name__ == "__main__":` guard is never True under
    # pytest (where __name__ is the package name), so it is at 0% without this test.
    # runpy.run_module sets __name__ = "__main__", triggering the block in-process.
    import runpy
    from unittest.mock import patch

    with patch("looptight.cli.main", return_value=0):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("looptight", run_name="__main__", alter_sys=True)
    assert exc_info.value.code == 0


def test_init_integrate_reports_already_installed_on_rerun(tmp_path, monkeypatch, capsys):
    # commands.py:136 — when init --integrate is re-run in a directory where session
    # and goal loops are already present, state is "already installed" not "installed".
    # Without this test, a regression dropping the `else` branch or changing the
    # state string would be invisible to the suite.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')

    assert main(["init", "--integrate"]) == 0
    capsys.readouterr()  # discard first-run output

    assert main(["init", "--integrate"]) == 0
    out = capsys.readouterr().out
    assert "already installed" in out
