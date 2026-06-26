"""The looptight skill for Claude Code.

`install-skill` drops a SKILL.md into ``~/.claude/skills/looptight/`` so Claude Code
discovers looptight in any session and knows when to reach for it. The content is
embedded here so it ships with the installed package and needs no package data.
"""

from __future__ import annotations

from pathlib import Path

SKILL_MD = """---
name: looptight
description: Use when the user wants a test-gated work loop, to burn down a backlog \
(TODOs, skipped tests, lint) with a test gate, or to build/refine a repository \
autonomously. Covers the looptight CLI (init, next, verify, propose, goal), which \
selects grounded tasks and gates commits on the project's own tests, inside the \
current session, making no model or network calls itself.
---

# looptight

looptight is a test-gated work loop that runs inside this agent session. It picks a
grounded task, you implement it, it runs the project's verify command, and a commit is
authorized only when verification passes. looptight makes no model or network calls of
its own; this session does the building.

## When to use

- The user wants to work through a backlog (TODOs, skipped tests, lint findings) with a
  real test gate on each change.
- The user wants the repository to keep improving, every change gated by its tests.
- The user wants to build a project toward a stated vision from scratch (goal mode).

## The loop (run inside this session)

1. `looptight next --json` returns one grounded task, or NO_WORK.
2. Implement exactly that task.
3. `looptight verify --json`; only a `pass` authorizes a commit.
4. Commit the coherent change, then repeat.

On NO_WORK carrying a generate_ideas directive, add 1 to 6 evidence-backed tasks as a
numbered list (each with an `Evidence:` path and an observable `Acceptance:`; `-` bullets
are not parsed) to docs/STATUS.md, then continue. Stop when no evidence-backed work remains.

## Build toward a goal (0 to 1)

- `looptight goal "<vision>" [--done CMD] [--continuous] [--max-iterations N]` sets a goal.
- `looptight goal next` hands you one verify-gated increment; build it, run
  `looptight verify`, commit, repeat.
- `looptight goal check` exits 0 when the done-check passes, so a native loop can drive
  it hands-off: `/loop until: looptight goal check`.

## Setup

`looptight init --integrate` writes the loop instructions into this repository's
CLAUDE.md and AGENTS.md so the loop runs without re-prompting. Do not run `looptight
run` or `looptight improve` from the session loop; those launch separate child agents.
"""


def skill_path(home: Path | None = None) -> Path:
    """Where the looptight SKILL.md lives for Claude Code."""
    base = home if home is not None else Path.home()
    return base / ".claude" / "skills" / "looptight" / "SKILL.md"


def install_skill(home: Path | None = None) -> Path:
    """Write the looptight skill for Claude Code and return its path."""
    path = skill_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SKILL_MD, encoding="utf-8")
    return path
