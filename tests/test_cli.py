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
