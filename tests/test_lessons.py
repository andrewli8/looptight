"""Lesson persistence + hygiene (C2, C3, C4)."""

from __future__ import annotations

from looptight.lessons import BLOCK_END, BLOCK_START, LessonStore, parse_lessons
from looptight.types import Lesson


def test_add_creates_block_in_fresh_file(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    assert store.add(Lesson(text="Use absolute imports in src/")) is True
    content = (workdir / "CLAUDE.md").read_text()
    assert BLOCK_START in content and BLOCK_END in content
    assert "Use absolute imports" in content


def test_add_preserves_existing_memory_content(workdir):
    memory = workdir / "CLAUDE.md"
    memory.write_text("# Project notes\n\nSome existing guidance.\n")
    store = LessonStore(memory)
    store.add(Lesson(text="Pin the timeout"))
    content = memory.read_text()
    assert "Some existing guidance." in content
    assert "Pin the timeout" in content


def test_dedupes_normalized_text(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    assert store.add(Lesson(text="Pin the timeout to 30s")) is True
    assert store.add(Lesson(text="  pin   the TIMEOUT to 30s ")) is False  # same after normalize
    assert len(store.list()) == 1


def test_scope_distinguishes_lessons(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    store.add(Lesson(text="Mock the clock", scope="tests"))
    store.add(Lesson(text="Mock the clock", scope="types"))
    assert len(store.list()) == 2


def test_prune_all_and_by_match(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    store.add(Lesson(text="thing about retries"))
    store.add(Lesson(text="thing about caching"))
    assert store.prune(contains="retries") == 1
    assert len(store.list()) == 1
    assert store.prune() == 1  # clear the rest
    assert store.list() == []


def test_roundtrip_parse(workdir):
    store = LessonStore(workdir / "AGENTS.md")
    store.add(Lesson(text="Close the file handle", scope="io"))
    parsed = parse_lessons((workdir / "AGENTS.md").read_text())
    assert parsed[0].text == "Close the file handle"
    assert parsed[0].scope == "io"
