"""Grounded task decisions for the current native agent session."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from .claims import ClaimStore, claim_dir, owner_id
from .coordinator import Coordinator, current_run_id
from .prompts import IDEA_DIRECTIVE_ACTION, PLANNING_GOAL
from .propose import Candidate, propose

ProposeFn = Callable[..., list[Candidate]]


@dataclass(frozen=True)
class NextResult:
    status: str
    task: dict[str, str | None] | None = None
    error: str | None = None
    directive: dict[str, object] | None = None
    schema_version: int = 1

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "command": "next",
            "status": self.status,
            "task": self.task,
        }
        if self.error is not None:
            payload["error"] = self.error
        if self.directive is not None:
            payload["directive"] = self.directive
        return payload


def _summary_and_evidence(candidate: Candidate) -> tuple[str, str]:
    """Split a candidate into a short summary and its grounding evidence.

    Status/task-file items carry their `Evidence:` pointers inline in the title;
    pull those into the evidence field so `goal` stays a concise directive instead
    of repeating the whole paragraph. Ad-hoc signals (todo/lint/skipped) have no
    inline marker, so their raw detail line is the evidence.
    """
    head, marker, refs = candidate.title.partition("Evidence:")
    if marker:
        return head.strip().rstrip(".;"), (marker + refs).strip()
    return candidate.title.strip(), candidate.detail.strip()


def _grounded_goal(summary: str, location: str | None) -> str:
    where = f" at {location}" if location else ""
    return (
        f"Implement exactly one grounded repository improvement: {summary}{where}. "
        "Inspect the evidence, make the smallest safe change, and leave verification to looptight."
    )


def _has_dirty_git_worktree(workdir: Path) -> bool:
    """Treat tracked and untracked changes as unsafe for a new task claim."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _idea_directive() -> dict[str, object]:
    """Directive telling a host session to generate grounded tasks on an empty queue."""
    return {"action": IDEA_DIRECTIVE_ACTION, "prompt": PLANNING_GOAL, "max_tasks": 6}


def next_task(
    workdir: Path,
    *,
    propose_fn: ProposeFn = propose,
    idea_generation: bool = True,
    run_id: str | None = None,
) -> NextResult:
    """Claim one grounded task without making an agent or network call.

    When the grounded queue is empty and ``idea_generation`` is enabled, the
    ``no_work`` result carries a directive instructing the host session to
    generate grounded tasks rather than stop. looptight itself makes no call.
    """
    if _has_dirty_git_worktree(workdir):
        return NextResult(status="error", error="dirty_worktree")
    candidates = propose_fn(workdir, limit=0)

    tasks: list[dict[str, str | None]] = []
    for candidate in candidates:
        if not all((candidate.title.strip(), candidate.detail.strip(), candidate.acceptance.strip())):
            continue
        # Discovery routing may change (for example, a status file can become an
        # explicitly configured task file) without changing the underlying task.
        # Keep claims stable across those equivalent sources.
        identity = "\0".join((candidate.location or "", candidate.title))
        summary, evidence = _summary_and_evidence(candidate)
        tasks.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:12],
                "source": candidate.source,
                "location": candidate.location,
                "goal": _grounded_goal(summary, candidate.location),
                "evidence": evidence,
                "acceptance": candidate.acceptance,
                "suggested_verify": candidate.suggested_verify,
            }
        )

    coordinator = Coordinator.open(workdir)
    if coordinator is not None:
        run_id = run_id or current_run_id()
        coordinator.start_run("session", run_id=run_id)
        lease = coordinator.claim(cast(list[dict[str, object]], tasks), run_id, ttl_s=24 * 60 * 60)
        task = cast(dict[str, str | None] | None, lease.payload if lease else None)
        coordinator.close()
    else:
        private_dir = claim_dir(workdir)
        if private_dir is None:
            task = tasks[0] if tasks else None
        else:
            task = ClaimStore(private_dir, owner_id(workdir)).select(tasks)
    if task:
        return NextResult(status="task", task=task)
    return NextResult(status="no_work", directive=_idea_directive() if idea_generation else None)
