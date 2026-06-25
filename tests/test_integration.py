from __future__ import annotations

import pytest

from looptight.config import ConfigError
from looptight.integration import END, SESSION_LOOP, START, install_session_instructions


def test_installs_same_small_loop_for_all_agents(tmp_path):
    changed = install_session_instructions(tmp_path)

    assert changed == [tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"]
    assert (tmp_path / "AGENTS.md").read_text() == SESSION_LOOP
    assert (tmp_path / "CLAUDE.md").read_text() == SESSION_LOOP
    assert "looptight next --json" in SESSION_LOOP
    assert "looptight verify --json" in SESSION_LOOP
    assert "Do not run `looptight run` or `looptight improve`" in SESSION_LOOP
    # The loop generates grounded tasks on an empty queue by default, with an escape.
    assert "generate_ideas" in SESSION_LOOP
    assert "--no-ideas" in SESSION_LOOP


def test_install_repairs_start_marker_without_matching_end(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"# Existing\n\nKeep this.\n\n{START}\norphaned managed block, no end\n")

    changed = install_session_instructions(tmp_path)

    text = path.read_text()
    assert path in changed
    assert text.count(START) == 1
    assert text.count(END) == 1
    assert "Keep this." in text
    assert "orphaned managed block, no end" not in text
    assert text.endswith(SESSION_LOOP)


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


def test_install_raises_clear_error_on_non_utf8_file_without_partial_write(tmp_path):
    # A non-UTF-8 managed-block file must produce a clear ConfigError naming the
    # file, not a raw UnicodeDecodeError, and no other file may be written first.
    (tmp_path / "CLAUDE.md").write_bytes(b"\xff\xfe not utf-8")

    with pytest.raises(ConfigError) as exc:
        install_session_instructions(tmp_path)

    assert "CLAUDE.md" in str(exc.value)
    # AGENTS.md is processed first in the loop; validation must happen before any
    # write, so it is never created when CLAUDE.md cannot be read.
    assert not (tmp_path / "AGENTS.md").exists()


def test_install_writes_managed_block_atomically(tmp_path, monkeypatch):
    # An interrupted write must not corrupt a user's instructions file: if the
    # rename fails, the original AGENTS.md is intact and no .tmp is left behind.
    import looptight.integration as integration

    original = "# My project notes\n"
    (tmp_path / "AGENTS.md").write_text(original, encoding="utf-8")

    def boom(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr(integration.os, "replace", boom)
    with pytest.raises(OSError):
        install_session_instructions(tmp_path)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == original
    assert not (tmp_path / "AGENTS.tmp").exists()
