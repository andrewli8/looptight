"""CLI smoke tests — the commands wire up and exit cleanly."""

from __future__ import annotations

import json
import subprocess

import pytest

from looptight.cli import main
from looptight.protocol_commands import _verify_exit_code


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


def test_next_returns_no_work_when_no_signals(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["next"]) == 0
    assert capsys.readouterr().out.strip() == "NO_WORK"


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
    monkeypatch.chdir(tmp_path)
    assert main(["next", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "schema_version": 1,
        "command": "next",
        "status": "no_work",
        "task": None,
    }


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
    assert "looptight init" in data["next_action"]
    assert list(tmp_path.iterdir()) == []


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


@pytest.mark.parametrize("value", ["0", "-1"])
def test_run_rejects_non_positive_max_iterations(value):
    with pytest.raises(SystemExit) as exc:
        main(["run", "goal", "--max-iterations", value])

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
