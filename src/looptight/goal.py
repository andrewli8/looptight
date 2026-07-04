"""Repo-private goal state for the vision-driven ``looptight goal`` build loop.

The goal is a north star the host session builds toward, one verify-gated increment
at a time. State lives beside the coordinator under the git common dir, so it is
shared across worktrees and never enters project history. No model calls.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable

from .coordinator import coordinator_path
from .fsutil import atomic_write_text
from .prompts import goal_build

SCHEMA_VERSION = 1
_GOAL_FILE = "goal.json"

CheckRunner = Callable[[Path, str], bool]


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
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            return None
        return Goal(
            vision=str(data.get("vision", "")),
            done_check=data.get("done_check"),
            continuous=bool(data.get("continuous", False)),
            max_iterations=int(data.get("max_iterations", 0)),
            iteration=int(data.get("iteration", 0)),
        )
    except (OSError, ValueError, TypeError):
        # ValueError covers json.JSONDecodeError and UnicodeDecodeError.
        # TypeError is raised when a JSON null coerces via int() (e.g. max_iterations: null).
        return None


def write_goal(workdir: Path, goal: Goal) -> None:
    """Atomically persist the goal to repo-private state."""
    path = goal_path(workdir)
    if path is None:
        raise RuntimeError("cannot store a goal outside a Git repository")
    atomic_write_text(path, json.dumps(goal.as_dict(), sort_keys=True) + "\n")


def clear_goal(workdir: Path) -> bool:
    """Remove the active goal; return True if one was present."""
    path = goal_path(workdir)
    if path is None or not path.is_file():
        return False
    path.unlink()
    return True


def run_done_check(workdir: Path, command: str, *, timeout: float = 60.0) -> bool:
    """Run a goal's --done command and return True on exit 0. Makes no model call.

    The command is a predicate: only its exit code matters, so its stdout/stderr are
    captured and discarded. Letting them through would pollute looptight's own stdout
    — corrupting ``goal check --json`` / ``goal next --json`` for the many done-checks
    (test runners, grep, make) that print as they run.
    """
    try:
        result = subprocess.run(
            command, shell=True, cwd=str(workdir), check=False, capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@dataclass(frozen=True)
class GoalDecision:
    """The result of one ``goal next``: keep building, stop, finish, or no goal."""

    status: str  # active | done | stop | no_goal
    directive: dict[str, object] | None = None
    reason: str | None = None
    iteration: int = 0
    schema_version: int = SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "command": "goal",
            "status": self.status,
            "iteration": self.iteration,
        }
        if self.directive is not None:
            payload["directive"] = self.directive
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def goal_next(workdir: Path, *, check_runner: CheckRunner = run_done_check) -> GoalDecision:
    """Decide the next step for the active goal without making a model call.

    Stops at the iteration cap, reports done when the --done check passes, otherwise
    emits one build directive for the host and advances the iteration counter.
    """
    goal = read_goal(workdir)
    if goal is None:
        return GoalDecision(status="no_goal")
    if goal.max_iterations and goal.iteration >= goal.max_iterations:
        return GoalDecision(status="stop", reason="max_iterations", iteration=goal.iteration)
    if goal.done_check and check_runner(workdir, goal.done_check):
        return GoalDecision(status="done", iteration=goal.iteration)
    advanced = replace(goal, iteration=goal.iteration + 1)
    write_goal(workdir, advanced)
    directive = {
        "action": "build_increment",
        "prompt": goal_build(goal.vision),
        "done_check": goal.done_check,
    }
    return GoalDecision(status="active", directive=directive, iteration=advanced.iteration)
