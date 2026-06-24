"""The looptight skill install for Claude Code discovery."""

from __future__ import annotations

from looptight.cli import main
from looptight.skill import install_skill, skill_path


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


def test_install_skill_cli_uses_the_home_skills_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert main(["install-skill"]) == 0
    installed = tmp_path / ".claude" / "skills" / "looptight" / "SKILL.md"
    assert installed.is_file()
    assert "installed" in capsys.readouterr().out
