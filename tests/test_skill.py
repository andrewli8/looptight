"""The looptight skill install for Claude Code discovery."""

from __future__ import annotations

from looptight.cli import main
from looptight.skill import SKILL_MD, install_skill, skill_path


def test_install_skill_writes_skill_md(tmp_path):
    path = install_skill(home=tmp_path)
    assert path == skill_path(tmp_path)
    assert path == tmp_path / ".claude" / "skills" / "looptight" / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")  # frontmatter for Claude Code discovery
    assert "name: looptight" in text
    assert "description:" in text
    assert "looptight verify" in text  # documents the core loop
    assert "looptight goal" in text  # documents goal mode


def test_install_skill_overwrites_stale_content(tmp_path):
    path = install_skill(home=tmp_path)
    path.write_text("stale content", encoding="utf-8")
    install_skill(home=tmp_path)
    assert path.read_text(encoding="utf-8") == SKILL_MD


def test_install_skill_cli_uses_the_home_skills_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["install-skill"]) == 0
    installed = tmp_path / ".claude" / "skills" / "looptight" / "SKILL.md"
    assert installed.is_file()
    assert "installed" in capsys.readouterr().out


def test_install_skill_cli_reports_already_up_to_date_on_no_op_rerun(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["install-skill"]) == 0
    capsys.readouterr()  # discard first-run output
    assert main(["install-skill"]) == 0  # second run: content unchanged
    out = capsys.readouterr().out.lower()
    assert "up to date" in out
    assert "installed the looptight skill" not in out


def test_init_hints_at_install_skill_under_claude_code(tmp_path, monkeypatch, capsys):
    # init stays project-scoped (it does not write the global skill), but it points
    # the user to install-skill when Claude Code is the detected agent.
    from looptight import commands

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(commands, "detect_agent", lambda *a, **k: "claude")
    assert main(["init"]) == 0
    assert "install-skill" in capsys.readouterr().out


def test_install_skill_atomic_write_cleans_up_on_os_replace_failure(tmp_path, monkeypatch):
    path = skill_path(tmp_path)
    tmp_file = path.with_suffix(".tmp")

    def boom(src, dst):
        raise OSError("injected failure")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)

    try:
        install_skill(home=tmp_path)
    except OSError:
        pass
    else:
        raise AssertionError("OSError should have been re-raised")

    assert not tmp_file.exists(), "stale .tmp must be removed on failure"
    assert not path.exists(), "target must not exist after a failed write"


def test_install_skill_tolerates_non_utf8_existing_file(tmp_path, monkeypatch, capsys):
    # A non-UTF-8 SKILL.md must not crash `install-skill`: the "already up to date"
    # read should treat an unreadable file as not-current and rewrite, matching the
    # (OSError, ValueError) handling used by the other readers. UnicodeDecodeError is
    # a ValueError, not an OSError, so an `except OSError`-only guard misses it.
    monkeypatch.setenv("HOME", str(tmp_path))
    path = skill_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not valid utf-8")

    assert main(["install-skill"]) == 0  # must not raise
    assert path.read_text(encoding="utf-8") == SKILL_MD  # rewritten cleanly
