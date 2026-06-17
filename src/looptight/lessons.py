"""The learning layer — persistence + hygiene (C2, C3, C4).

Lessons live in a single delimited block inside the agent's own memory file
(``CLAUDE.md`` / ``AGENTS.md`` / opencode config). Because they're in the file
the agent always reads, they keep working even when looptight isn't running, and
they compound across runs and goals (C3) — which a per-thread native goal state
structurally can't do.

Hygiene (C4): lessons are deduped by normalized text, scoped, and prunable with
one command. A wrong lesson poisons every future session, so this is the
riskiest surface and gets first-class treatment.
"""

from __future__ import annotations

import re
from pathlib import Path

from .types import Lesson

BLOCK_START = "<!-- looptight:lessons:start -->"
BLOCK_END = "<!-- looptight:lessons:end -->"
BLOCK_HEADING = "## Lessons (looptight)"

_BLOCK_RE = re.compile(
    re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END),
    re.DOTALL,
)
_BULLET_RE = re.compile(r"^- \[(?P<date>[^\]]+)\]\s*(?:\(scope:\s*(?P<scope>[^)]*)\)\s*)?(?P<text>.+)$")


def parse_lessons(content: str) -> list[Lesson]:
    """Extract the lessons currently stored in a memory file's content."""
    match = _BLOCK_RE.search(content)
    if not match:
        return []
    lessons: list[Lesson] = []
    for line in match.group(0).splitlines():
        bullet = _BULLET_RE.match(line.strip())
        if bullet:
            lessons.append(
                Lesson(
                    text=bullet.group("text").strip(),
                    scope=(bullet.group("scope") or "*").strip() or "*",
                    created_at=bullet.group("date").strip(),
                )
            )
    return lessons


def _render_block(lessons: list[Lesson]) -> str:
    body = "\n".join(lesson.render() for lesson in lessons) if lessons else "- (none yet)"
    return f"{BLOCK_START}\n{BLOCK_HEADING}\n\n{body}\n{BLOCK_END}"


def _write_block(content: str, lessons: list[Lesson]) -> str:
    block = _render_block(lessons)
    if _BLOCK_RE.search(content):
        return _BLOCK_RE.sub(lambda _: block, content)
    separator = "" if content.endswith("\n") or content == "" else "\n"
    prefix = content + separator + ("\n" if content.strip() else "")
    return f"{prefix}{block}\n"


class LessonStore:
    """Reads and writes the lessons block in a single memory file."""

    def __init__(self, memory_file: Path):
        self.memory_file = memory_file

    def _read(self) -> str:
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.is_file() else ""

    def list(self) -> list[Lesson]:
        return parse_lessons(self._read())

    def add(self, lesson: Lesson) -> bool:
        """Add a lesson, deduped by normalized text+scope (C4).

        Returns True if it was new, False if a duplicate was suppressed.
        """
        existing = self.list()
        if any(item.key == lesson.key for item in existing):
            return False
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(_write_block(self._read(), [*existing, lesson]), encoding="utf-8")
        return True

    def prune(self, contains: str | None = None) -> int:
        """Remove lessons. With ``contains``, only matching ones; else all.

        Returns the number removed.
        """
        existing = self.list()
        if contains is None:
            kept: list[Lesson] = []
        else:
            needle = contains.lower()
            kept = [item for item in existing if needle not in item.text.lower()]
        removed = len(existing) - len(kept)
        if removed:
            self.memory_file.write_text(_write_block(self._read(), kept), encoding="utf-8")
        return removed
