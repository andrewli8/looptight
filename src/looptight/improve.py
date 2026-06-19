"""Continuous, verify-gated repository improvement orchestration."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from .checkpoint import Checkpointer, is_git_repo
from .propose import Candidate, propose
from .types import RunResult, StopReason


class ImproveStopReason(str, Enum):
    SESSION_BUDGET = "session_budget"
    PROVIDER_STOP = "provider_stop"
    INTERRUPTED = "interrupted"
    GIT_ERROR = "git_error"


@dataclass(frozen=True)
class ImproveResult:
    stop_reason: ImproveStopReason
    tasks_attempted: int = 0
    commits: int = 0
    total_cost_usd: float = 0.0
    error: str | None = None


GitFn = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
RunTaskFn = Callable[[str, Checkpointer], RunResult]
ProposeFn = Callable[..., list[Candidate]]
EventFn = Callable[[str], None]


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )


def _status(git_fn: GitFn, workdir: Path) -> subprocess.CompletedProcess[str]:
    return git_fn(["status", "--porcelain"], workdir)


def _candidate_key(candidate: Candidate) -> tuple[str | None, str]:
    return candidate.location, " ".join(candidate.title.lower().split())


def _grounded_goal(candidate: Candidate) -> str:
    location = f" at {candidate.location}" if candidate.location else ""
    return (
        f"Implement exactly one grounded repository improvement: {candidate.title}{location}. "
        "Inspect the evidence, make the smallest safe change, and leave verification to looptight."
    )


def _audit_goal(number: int, outcomes: list[str]) -> str:
    recent = "; ".join(outcomes[-5:]) or "none"
    return (
        f"Repository improvement audit #{number}. Inspect the repository and implement exactly one "
        "new, high-value, evidence-backed improvement. Prior session outcomes: "
        f"{recent}. Choose a different concrete area; avoid speculative behavior, test padding, "
        "and duplicate documentation. Do not edit REVIEW-QUEUE.md, add STATUS run logs, or change "
        "other documentation merely to report that no work was found. If there is no "
        "evidence-backed improvement, leave the working tree unchanged. Legitimate product "
        "documentation remains allowed when it is the actual evidence-backed improvement. Leave "
        "verification to looptight."
    )


def _commit_subject(candidate: Candidate | None, number: int) -> str:
    raw = candidate.title if candidate else f"autonomous repository improvement {number}"
    clean = re.sub(r"[`\r\n]+", "", raw).strip().rstrip(".")
    clean = " ".join(clean.split())
    if len(clean) > 68:
        # Cut on a word boundary so the subject never ends mid-word.
        clean = clean[:68].rsplit(" ", 1)[0].rstrip()
    return f"chore: {clean or f'autonomous repository improvement {number}'}"


def _rollback(
    checkpointer: Checkpointer,
    snapshot: str,
    git_fn: GitFn,
    workdir: Path,
) -> str | None:
    reset = git_fn(["reset", "--mixed", snapshot], workdir)
    if reset.returncode != 0:
        return reset.stderr.strip() or "failed to reset task index"
    if not checkpointer.restore(snapshot):
        return "failed to restore tracked files"
    cleaned = git_fn(["clean", "-fd"], workdir)
    if cleaned.returncode != 0:
        return cleaned.stderr.strip() or "failed to remove task-created untracked files"
    status = _status(git_fn, workdir)
    if status.returncode != 0 or status.stdout.strip():
        return status.stderr.strip() or "working tree is not clean after rollback"
    return None


def run_improve(
    workdir: Path,
    run_task: RunTaskFn,
    *,
    propose_fn: ProposeFn = propose,
    session_budget_usd: float | None = None,
    push: bool = False,
    git_fn: GitFn = _git,
    on_event: EventFn | None = None,
) -> ImproveResult:
    """Continuously discover and run improvements until an explicit stop."""
    if not is_git_repo(workdir):
        return ImproveResult(ImproveStopReason.GIT_ERROR, error="improve requires a Git repository")
    initial = _status(git_fn, workdir)
    if initial.returncode != 0 or initial.stdout.strip():
        return ImproveResult(
            ImproveStopReason.GIT_ERROR,
            error=initial.stderr.strip() or "improve requires a clean working tree",
        )
    if session_budget_usd is not None and session_budget_usd <= 0:
        return ImproveResult(ImproveStopReason.SESSION_BUDGET)

    attempted: set[tuple[str | None, str]] = set()
    outcomes: list[str] = []
    tasks = 0
    commits = 0
    spent = 0.0
    audit_number = 0

    while True:
        candidates = propose_fn(workdir, limit=0)
        candidate = next((c for c in candidates if _candidate_key(c) not in attempted), None)
        if candidate is not None:
            attempted.add(_candidate_key(candidate))
            goal = _grounded_goal(candidate)
        else:
            audit_number += 1
            goal = _audit_goal(audit_number, outcomes)

        checkpointer = Checkpointer(workdir)
        snapshot = checkpointer.snapshot()
        if snapshot is None:
            return ImproveResult(
                ImproveStopReason.GIT_ERROR, tasks, commits, spent, "failed to create task checkpoint"
            )
        if on_event:
            on_event(f"task {tasks + 1}: {candidate.title if candidate else f'audit #{audit_number}'}")

        try:
            result = run_task(goal, checkpointer)
        except KeyboardInterrupt:
            error = _rollback(checkpointer, snapshot, git_fn, workdir)
            reason = ImproveStopReason.GIT_ERROR if error else ImproveStopReason.INTERRUPTED
            return ImproveResult(reason, tasks, commits, spent, error)

        tasks += 1
        spent += max(0.0, result.total_cost_usd)

        if result.stop_reason in {StopReason.ERROR, StopReason.AGENT_UNAVAILABLE}:
            error = _rollback(checkpointer, snapshot, git_fn, workdir)
            return ImproveResult(
                ImproveStopReason.GIT_ERROR if error else ImproveStopReason.PROVIDER_STOP,
                tasks,
                commits,
                spent,
                error
                or result.error
                or (
                    "coding agent unavailable"
                    if result.stop_reason is StopReason.AGENT_UNAVAILABLE
                    else "coding provider stopped"
                ),
            )

        if result.passed:
            status = _status(git_fn, workdir)
            if status.returncode != 0:
                return ImproveResult(
                    ImproveStopReason.GIT_ERROR,
                    tasks,
                    commits,
                    spent,
                    status.stderr.strip() or "failed to inspect working tree",
                )
            if status.stdout.strip():
                added = git_fn(["add", "-A"], workdir)
                subject = _commit_subject(candidate, tasks)
                committed = git_fn(["commit", "-m", subject], workdir) if added.returncode == 0 else added
                if committed.returncode != 0:
                    error = _rollback(checkpointer, snapshot, git_fn, workdir)
                    return ImproveResult(
                        ImproveStopReason.GIT_ERROR,
                        tasks,
                        commits,
                        spent,
                        error or committed.stderr.strip() or "git commit failed",
                    )
                commits += 1
                outcomes.append(f"committed {subject}")
                if push:
                    pushed = git_fn(["push"], workdir)
                    if pushed.returncode != 0:
                        return ImproveResult(
                            ImproveStopReason.GIT_ERROR,
                            tasks,
                            commits,
                            spent,
                            pushed.stderr.strip() or "git push failed",
                        )
            else:
                outcomes.append(f"no changes from {candidate.title if candidate else f'audit #{audit_number}'}")
        else:
            error = _rollback(checkpointer, snapshot, git_fn, workdir)
            if error:
                return ImproveResult(ImproveStopReason.GIT_ERROR, tasks, commits, spent, error)
            outcomes.append(
                f"unverified {candidate.title if candidate else f'audit #{audit_number}'}"
            )

        if session_budget_usd is not None and spent >= session_budget_usd:
            return ImproveResult(ImproveStopReason.SESSION_BUDGET, tasks, commits, spent)
