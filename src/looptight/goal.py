"""Repo-private goal state for the vision-driven ``looptight goal`` build loop.

The goal is a north star the host session builds toward, one verify-gated increment
at a time. State lives beside the coordinator under the git common dir, so it is
shared across worktrees and never enters project history. No model calls.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .coordinator import coordinator_path

SCHEMA_VERSION = 1
_GOAL_FILE = "goal.json"


def goal_path(workdir: Path) -> Path | None:
    """Repo-private ``goal.json`` path (beside the coordinator), or None outside Git."""
    coordinator = coordinator_path(workdir)
    if coordinator is None:
        return None
    return coordinator.parent / _GOAL_FILE


@dataclass(frozen=True)
class Goal:
    """An active build goal: the vision and how the loop should run and stop."""

    vision: str
    done_check: str | None = None
    continuous: bool = False
    max_iterations: int = 0
    iteration: int = 0
    schema_version: int = SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def read_goal(workdir: Path) -> Goal | None:
    """Return the active goal, or None when absent, unreadable, or a wrong schema."""
    path = goal_path(workdir)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    return Goal(
        vision=str(data.get("vision", "")),
        done_check=data.get("done_check"),
        continuous=bool(data.get("continuous", False)),
        max_iterations=int(data.get("max_iterations", 0)),
        iteration=int(data.get("iteration", 0)),
    )


def write_goal(workdir: Path, goal: Goal) -> None:
    """Atomically persist the goal to repo-private state."""
    path = goal_path(workdir)
    if path is None:
        raise RuntimeError("cannot store a goal outside a Git repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(goal.as_dict(), sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def clear_goal(workdir: Path) -> bool:
    """Remove the active goal; return True if one was present."""
    path = goal_path(workdir)
    if path is None or not path.is_file():
        return False
    path.unlink()
    return True
