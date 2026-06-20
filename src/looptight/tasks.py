"""Grounded task decisions for the current native agent session."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .claims import ClaimStore, claim_dir, owner_id
from .propose import Candidate, propose

ProposeFn = Callable[..., list[Candidate]]


@dataclass(frozen=True)
class NextResult:
    status: str
    task: dict[str, str | None] | None = None
    schema_version: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "command": "next",
            "status": self.status,
            "task": self.task,
        }


def _grounded_goal(candidate: Candidate) -> str:
    location = f" at {candidate.location}" if candidate.location else ""
    return (
        f"Implement exactly one grounded repository improvement: {candidate.title}{location}. "
        "Inspect the evidence, make the smallest safe change, and leave verification to looptight."
    )


def next_task(workdir: Path, *, propose_fn: ProposeFn = propose) -> NextResult:
    """Claim one grounded task without making an agent or network call."""
    candidates = propose_fn(workdir, limit=0)
    if not candidates:
        return NextResult(status="no_work")

    tasks: list[dict[str, str | None]] = []
    for candidate in candidates:
        if not all((candidate.title.strip(), candidate.detail.strip(), candidate.acceptance.strip())):
            continue
        identity = "\0".join((candidate.source, candidate.location or "", candidate.title))
        tasks.append(
            {
                "id": hashlib.sha256(identity.encode()).hexdigest()[:12],
                "source": candidate.source,
                "location": candidate.location,
                "goal": _grounded_goal(candidate),
                "evidence": candidate.detail,
                "acceptance": candidate.acceptance,
                "suggested_verify": candidate.suggested_verify,
            }
        )

    private_dir = claim_dir(workdir)
    task = (
        tasks[0]
        if private_dir is None
        else ClaimStore(private_dir, owner_id(workdir)).select(tasks)
    )
    return NextResult(status="task", task=task) if task else NextResult(status="no_work")
