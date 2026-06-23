"""CLI smoke tests — the commands wire up and exit cleanly."""

from __future__ import annotations

import json
import subprocess

import pytest

from looptight.cli import build_parser, main
from looptight.protocol_commands import _verify_exit_code
from looptight.propose import propose


def test_run_parser_accepts_resume_on_limit_flags():
    args = build_parser().parse_args(
        ["run", "--headless", "g", "--resume-on-limit", "--limit-backoff-seconds", "15"]
    )
    assert args.resume_on_limit is True
    assert args.limit_backoff_seconds == 15.0
    assert args.limit_max_wait_seconds == 3600.0


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
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")
    assert main(["next"]) == 0
    assert "fix the timeout" in capsys.readouterr().out


def test_next_human_output_shows_acceptance_without_changing_json(
    tmp_path, monkeypatch, capsys
):
    # A person running `looptight next` should see the observable done-criterion,
    # not just the goal, while the machine `--json` decision stays unchanged.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")

    assert main(["next"]) == 0
    human = capsys.readouterr().out
    assert "fix the timeout" in human
    assert "Remove the marker" in human

    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "Remove the marker" in data["task"]["acceptance"]
    assert set(data) == {"schema_version", "command", "status", "task"}


def test_next_no_work_directs_idea_generation_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["next"]) == 0
    out = capsys.readouterr().out
    assert "NO_WORK" in out
    assert "--no-ideas" in out  # the default offers idea generation rather than stopping


def test_next_no_work_is_bare_with_no_ideas(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["next", "--no-ideas"]) == 0
    assert capsys.readouterr().out.strip() == "NO_WORK"


def test_next_json_no_work_directs_idea_generation_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "no_work"
    assert data["directive"]["action"] == "generate_ideas"
    assert "docs/STATUS.md" in data["directive"]["prompt"]


def test_next_json_contract_is_grounded_and_stable(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: fix the timeout\n")

    assert main(["next", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
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


def test_next_json_no_work_contract(tmp_path, monkeypatch, capsys):
    # With idea generation off, the no_work payload is the bare, stable contract.
    monkeypatch.chdir(tmp_path)
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
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "# S\n\n## Next\n\n"
        "1. Cover the thing module. Evidence: src/thing.py:1; "
        "Acceptance: a test imports thing and passes.\n",
        encoding="utf-8",
    )

    assert main(["next", "--json"]) == 0
    task = json.loads(capsys.readouterr().out)["task"]
    assert "Cover the thing module" in task["goal"]
    assert "Evidence:" not in task["goal"]  # grounding no longer duplicated into goal
    assert "Acceptance:" not in task["goal"]
    assert task["evidence"] == "Evidence: src/thing.py:1"
    assert "a test imports thing" in task["acceptance"]


def test_next_human_explains_task_selection(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text(
        "# S\n\n## Next\n\n"
        "1. Cover the thing module. Evidence: src/thing.py:1; "
        "Acceptance: a test imports thing and passes.\n",
        encoding="utf-8",
    )

    assert main(["next"]) == 0

    out = capsys.readouterr().out
    assert "selected task:" in out
    assert "why: status-next from docs/STATUS.md" in out
    assert "evidence: Evidence: src/thing.py:1" in out
    assert "acceptance: a test imports thing and passes." in out
    assert "next: implement the task, then run `looptight verify --json`" in out


def test_next_and_swarm_parsers_accept_no_ideas():
    assert build_parser().parse_args(["next", "--no-ideas"]).no_ideas is True
    assert build_parser().parse_args(["swarm", "--headless", "--no-ideas"]).no_ideas is True


def test_next_json_reads_each_configured_task_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
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

    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "task"
    assert data["task"]["location"] == "TODO.md:1"
    assert "First configured task" in data["task"]["goal"]


def test_next_json_returns_no_work_for_empty_configured_sources(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text(
        'tasks = ["TODO.md"]\n', encoding="utf-8"
    )
    (tmp_path / "TODO.md").write_text("# No executable tasks\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: ignored fallback signal\n")

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
    assert data["readiness"]["checks"]["coordinator"] == "inactive"
    assert data["readiness"]["checks"]["task_sources"] == "missing"
    assert data["readiness"]["checks"]["agent"] == "missing"
    assert data["readiness"]["next_remediation"] == "run `looptight migrate`"


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
    assert "readiness next: run `looptight migrate`" in out


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


def test_status_human_reports_unsafe_concurrency_with_migrate_hint(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)

    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert "concurrency: unsafe" in out
    assert "concurrency next: run `looptight migrate`" in out


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
        "policy",
    }
    assert "verify" not in data


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


def test_doctor_hints_when_prerequisites_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # No verify command can be detected (empty dir) and no agent on PATH.
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "looptight init" in out  # remediation for missing verify
    assert "install one of" in out  # remediation for missing agent


def test_doctor_omits_hints_when_prerequisites_present(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest -q"\n')
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: "claude")
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "hint:" not in out  # both present → existing lines unchanged


def test_doctor_guides_setup_without_writing_or_starting_agents(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.commands.detect_agent", lambda *a, **k: None)

    assert main(["doctor"]) == 0

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


def test_malformed_config_exits_cleanly_not_traceback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text('verify = "pytest"\nbad = = toml\n')
    # A broken config must surface as a clean exit code, not an uncaught traceback.
    assert main(["doctor"]) == 2


def test_version_exits_zero(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0


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
    assert "verifier result: pass" in out
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


@pytest.mark.parametrize(
    ("status", "expected"),
    [("pass", 0), ("fail", 1), ("timeout", 2), ("error", 2)],
)
def test_verify_exit_codes_distinguish_verdict_from_execution_error(status, expected):
    assert _verify_exit_code(status) == expected


def test_propose_json_output(tmp_path, monkeypatch, capsys):
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

    rc = main(
        ["daemon", "--headless", "--workers", "2", "--model", "opus", "--push", "--max-cycles", "1"]
    )
    assert rc == 0
    assert captured["workers"] == 2
    assert captured["push"] is True
    assert captured["max_cycles"] == 1
    assert captured["config"].model == "opus"
    assert captured["resume_on_limit"] is True  # on by default for a 24/7 daemon
    out = capsys.readouterr().out
    assert "daemon stopped" in out
