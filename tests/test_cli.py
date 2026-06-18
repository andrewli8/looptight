"""CLI smoke tests — the commands wire up and exit cleanly."""

from __future__ import annotations

from looptight.cli import main


def test_init_writes_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert main(["init"]) == 0
    text = (tmp_path / ".looptight.toml").read_text()
    assert 'verify = "pytest -q"' in text


def test_bare_goal_defaults_to_run_but_needs_an_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.cli.detect_agent", lambda *a, **k: None)
    # No agent on PATH → clean exit code 2, not a crash.
    assert main(["fix the failing tests"]) == 2


def test_run_exits_error_when_no_verify_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.cli.detect_agent", lambda *a, **k: "claude")
    monkeypatch.setattr("looptight.cli.get_adapter", lambda name: __import__("conftest", fromlist=["FakeAdapter"]).FakeAdapter())
    # No config, no verify markers → no verify command → exit 2.
    assert main(["run", "fix tests"]) == 2


def test_doctor_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 0


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


def test_revert_reports_failure_when_git_checkout_fails(tmp_path, monkeypatch, capsys):
    import subprocess

    monkeypatch.chdir(tmp_path)
    # Pretend we're inside a git repo so revert proceeds past the guard.
    monkeypatch.setattr("looptight.cli.is_git_repo", lambda *a, **k: True)

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(args=a[0] if a else [], returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    # A failed checkout must surface a nonzero exit, not a green success message.
    assert main(["revert", "--yes"]) == 1
    out = capsys.readouterr().out.lower()
    assert "reverted" not in out
    assert "failed" in out
    assert "restore not confirmed" in out


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
