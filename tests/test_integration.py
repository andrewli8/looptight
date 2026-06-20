from __future__ import annotations

from looptight.integration import END, SESSION_LOOP, START, install_session_instructions


def test_installs_same_small_loop_for_all_agents(tmp_path):
    changed = install_session_instructions(tmp_path)

    assert changed == [tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"]
    assert (tmp_path / "AGENTS.md").read_text() == SESSION_LOOP
    assert (tmp_path / "CLAUDE.md").read_text() == SESSION_LOOP
    assert "looptight next --json" in SESSION_LOOP
    assert "looptight verify --json" in SESSION_LOOP
    assert "Do not run `looptight run` or `looptight improve`" in SESSION_LOOP


def test_install_is_idempotent_and_preserves_surrounding_instructions(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# Existing\n\nKeep this.\n")
    install_session_instructions(tmp_path)
    first = path.read_text()
    changed = install_session_instructions(tmp_path)

    assert path.read_text() == first
    assert path.read_text().count(START) == 1
    assert path.read_text().count(END) == 1
    assert "Keep this." in path.read_text()
    assert changed == []
