"""Reflection on failure (C1, D3).

When a run ends without passing, distill *one* short, specific lesson from the
transcript plus the verify output, using the adapter's cheap model (D3). The
lesson is meant to be actionable next time and scoped to where it applies.

Guardrail (C1): vague lessons are worse than none. If the cheap model isn't
available, or it returns something empty/too long/too generic, we return None
and write nothing rather than poisoning the memory file.
"""

from __future__ import annotations

from pathlib import Path

from .adapters.base import Adapter
from .lessons import BLOCK_END, BLOCK_START
from .types import Lesson, VerifyResult

_MAX_LESSON_CHARS = 240
_GENERIC = {
    "the test failed",
    "fix the code",
    "try again",
    "the code has a bug",
    "make the tests pass",
}

_PROMPT = """You are reviewing a coding attempt that did NOT pass its verification.

Goal: {goal}

Last verification output:
{verify}

Write ONE short, specific lesson (max 30 words) that would help avoid this exact
failure next time. Be concrete: name the file, function, edge case, or command
involved. Do not restate the goal. Do not be generic. If there is no specific,
reusable insight, reply with exactly: NONE

Lesson:"""


def _scope_from_verify(result: VerifyResult) -> str:
    """Best-effort scope tag from the verify command's output."""
    lowered = result.output.lower()
    for marker, scope in (("test", "tests"), ("type", "types"), ("lint", "lint")):
        if marker in lowered:
            return scope
    return "*"


def reflect_on_failure(
    adapter: Adapter,
    goal: str,
    verify: VerifyResult,
    workdir: Path,
) -> Lesson | None:
    """Produce a single durable Lesson, or None if there's nothing worth saving."""
    prompt = _PROMPT.format(goal=goal, verify=verify.output[-2000:] or "(no output)")
    raw = adapter.reflect(prompt, workdir)
    if not raw:
        return None

    text = raw.strip().strip("-•* ").strip()
    if not text or text.upper() == "NONE":
        return None
    # Reflection output is model-controlled and is persisted inside this
    # delimited block. Never let it terminate or create a lessons block.
    if BLOCK_START in text or BLOCK_END in text:
        return None
    if len(text) > _MAX_LESSON_CHARS:
        text = text[:_MAX_LESSON_CHARS].rsplit(" ", 1)[0] + "…"
    if " ".join(text.lower().split()) in _GENERIC:
        return None

    return Lesson(text=text, scope=_scope_from_verify(verify))
