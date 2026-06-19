"""CLI smoke tests — the commands wire up and exit cleanly."""

from __future__ import annotations

import pytest

from looptight.cli import main


def test_init_writes_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert main(["init"]) == 0
    text = (tmp_path / ".looptight.toml").read_text()
    assert 'verify = "pytest -q"' in text


def test_init_does_not_clobber_existing_config(tmp_path, monkeypatch, capsys):
    # Re-running init must not silently destroy a user's customized config.
    monkeypatch.chdir(tmp_path)
    existing = '# custom\nverify = "make check"\nbudget_usd = 5.0\n'
    (tmp_path / ".looptight.toml").write_text(existing)
    assert main(["init"]) == 0
    assert (tmp_path / ".looptight.toml").read_text() == existing  # untouched
    assert "exist" in capsys.readouterr().out.lower()


def test_bare_goal_defaults_to_run_but_needs_an_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)
    # No agent on PATH → clean exit code 2, not a crash.
    assert main(["fix the failing tests"]) == 2


def test_run_exits_error_when_no_verify_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter())
    # No config, no verify markers → no verify command → exit 2.
    assert main(["run", "fix tests"]) == 2


def test_main_handles_keyboard_interrupt_cleanly(monkeypatch, capsys):
    # Ctrl-C must exit cleanly (130), not dump a traceback, for any command.
    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("looptight.cli.cmd_doctor", boom)
    assert main(["doctor"]) == 130
    assert "interrupted" in capsys.readouterr().out.lower()


def test_run_banner_budget_honest_for_non_cost_reporting_agent(tmp_path, monkeypatch, capsys):
    # The startup banner must not show a dollar budget for an agent that reports
    # no cost — it can't be enforced, so don't imply it caps spend.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )
    main(["run", "fix it", "--verify", "exit 0", "--no-reflect"])
    out = " ".join(capsys.readouterr().out.lower().split())  # collapse rich line-wrapping
    assert "budget: not enforced" in out
    assert "budget: $" not in out


def test_run_warns_when_budget_cannot_be_enforced(tmp_path, monkeypatch, capsys):
    # A user who passes --budget to a no-cost-reporting agent (codex/opencode)
    # must be told it can't be enforced — same honesty as `improve` already has.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )
    main(["run", "fix it", "--verify", "exit 0", "--budget", "0.5"])
    out = capsys.readouterr().out.lower()
    assert "cannot enforce" in out
    assert "budget" in out


def test_run_exits_one_when_verify_never_passes(tmp_path, monkeypatch):
    # The primary command's failure exit code is a contract CI/scripts gate on:
    # a run that ends without a passing verify must return 1, not 0.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr(
        "looptight.commands.get_adapter",
        lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter(),
    )
    assert main(["run", "fix it", "--verify", "exit 1", "--max-iterations", "1", "--no-reflect"]) == 1


def test_doctor_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 0


def test_doctor_reports_config_path_when_present(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert ".looptight.toml" in out


def test_doctor_reports_no_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out.lower()
    assert "default" in out  # "none (using defaults)"


def test_malformed_config_exits_cleanly_not_traceback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest"\nbad = = toml\n')
    # A broken config must surface as a clean exit code, not an uncaught traceback.
    assert main(["doctor"]) == 2


def test_lessons_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["lessons", "--agent", "claude"]) == 0


def test_version_exits_zero(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0


def test_verify_passing_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "exit 0"]) == 0


def test_verify_failing_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify", "--verify", "exit 1"]) == 1


def test_verify_no_command_returns_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["verify"]) == 2


def test_propose_json_output(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["propose", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert any("fix the timeout" in c["title"] for c in data)


def test_propose_rejects_negative_cli_limit():
    with pytest.raises(SystemExit) as exc:
        main(["propose", "--limit", "-1"])

    assert exc.value.code == 2


@pytest.mark.parametrize("command", [["run", "goal"], ["improve"]])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_loop_commands_reject_non_positive_max_iterations(command, value):
    with pytest.raises(SystemExit) as exc:
        main([*command, "--max-iterations", value])

    assert exc.value.code == 2


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


def test_budget_flag_help_describes_spend_threshold(capsys):
    # --budget is a post-iteration spend stop, not an unexceedable ceiling: a
    # single agent call can overshoot it, so the help must not promise a ceiling.
    try:
        main(["run", "--help"])
    except SystemExit:
        pass
    out = capsys.readouterr().out.lower()
    assert "ceiling" not in out
    assert "spend" in out
    assert "overshoot" in out


def test_improve_summary_hides_dollar_cost_when_unreported(tmp_path, monkeypatch, capsys):
    # Consistent with the run summary: an agent that bills but reports no USD
    # must not show "$0.00 reported" (reads as free) in the improve summary line.
    from looptight.improve import ImproveResult, ImproveStopReason

    monkeypatch.chdir(tmp_path)
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()  # reports_cost_usd=False
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        "looptight.commands.run_improve",
        lambda *a, **k: ImproveResult(ImproveStopReason.NO_PROGRESS),
    )

    assert main(["improve", "--agent", "claude", "--verify", "exit 0"]) == 0
    out = capsys.readouterr().out.lower()
    assert "$0.00" not in out
    assert "cost not reported" in out


def test_improve_help_exposes_continuous_controls(capsys):
    try:
        main(["improve", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "--budget" in out
    assert "--push" in out
    assert "--max-iterations" in out


def test_improve_warns_when_provider_cost_cannot_be_measured(tmp_path, monkeypatch, capsys):
    from looptight.improve import ImproveResult, ImproveStopReason

    monkeypatch.chdir(tmp_path)
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        "looptight.commands.run_improve",
        lambda *a, **k: ImproveResult(ImproveStopReason.SESSION_BUDGET),
    )

    assert main(["improve", "--agent", "claude", "--verify", "exit 0", "--budget", "5"]) == 0
    out = capsys.readouterr().out.lower()
    assert "cannot enforce" in out
    assert "provider" in out


def test_improve_maps_provider_stop_to_failure(tmp_path, monkeypatch):
    from looptight.improve import ImproveResult, ImproveStopReason

    monkeypatch.chdir(tmp_path)
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        "looptight.commands.run_improve",
        lambda *a, **k: ImproveResult(
            ImproveStopReason.PROVIDER_STOP, error="usage limit reached"
        ),
    )

    assert main(["improve", "--agent", "claude", "--verify", "exit 0"]) == 1


def test_improve_maps_interrupt_to_130(tmp_path, monkeypatch):
    from looptight.improve import ImproveResult, ImproveStopReason

    monkeypatch.chdir(tmp_path)
    adapter = __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter()
    monkeypatch.setattr("looptight.commands.get_adapter", lambda name: adapter)
    monkeypatch.setattr(
        "looptight.commands.run_improve",
        lambda *a, **k: ImproveResult(ImproveStopReason.INTERRUPTED),
    )

    assert main(["improve", "--agent", "claude", "--verify", "exit 0", "--push"]) == 130


def test_revert_survives_oserror_when_listing_untracked(tmp_path, monkeypatch, capsys):
    # The post-revert `git ls-files` (untracked notice) must not crash the
    # command if git can't be launched for it — the revert already succeeded.
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.is_git_repo", lambda *a, **k: True)

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["git", "ls-files"]:
            raise OSError("git vanished")
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
    (tmp_path / "agent_made_this.py").write_text("new\n")  # untracked

    assert main(["revert", "--yes"]) == 0
    out = capsys.readouterr().out.lower()
    assert "reverted" in out
    assert "untracked" in out


def test_lessons_respects_configured_agent(tmp_path, monkeypatch, capsys):
    # With agent=codex in config, lessons must read AGENTS.md (codex's memory),
    # not fall back to a detected claude and read the wrong (empty) CLAUDE.md.
    from looptight.config import Config, write_config
    from looptight.lessons import LessonStore
    from looptight.types import Lesson

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    write_config(Config(verify="pytest -q", agent="codex"), tmp_path)
    LessonStore(tmp_path / "AGENTS.md").add(Lesson(text="Pin codex retries"))

    assert main(["lessons"]) == 0
    assert "Pin codex retries" in capsys.readouterr().out


def test_lessons_clear_removes_all(tmp_path, monkeypatch):
    from looptight.lessons import LessonStore
    from looptight.types import Lesson

    monkeypatch.chdir(tmp_path)
    store = LessonStore(tmp_path / "CLAUDE.md")
    store.add(Lesson(text="Pin the timeout in client.py"))
    assert main(["lessons", "--clear", "--agent", "claude"]) == 0
    assert store.list() == []


def test_lessons_prune_removes_matching(tmp_path, monkeypatch):
    from looptight.lessons import LessonStore
    from looptight.types import Lesson

    monkeypatch.chdir(tmp_path)
    store = LessonStore(tmp_path / "CLAUDE.md")
    store.add(Lesson(text="Pin the timeout in client.py"))
    store.add(Lesson(text="Always run the linter before committing"))
    assert main(["lessons", "--prune", "timeout", "--agent", "claude"]) == 0
    remaining = store.list()
    assert len(remaining) == 1
    assert "linter" in remaining[0].text
