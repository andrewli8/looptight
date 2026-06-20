"""Provision and launch a swarm of agent sessions across git worktrees.

A swarm is N coding-agent sessions working the same repository at once. Each
worker gets its own git worktree + branch — write isolation, plus a distinct
claim identity — and runs the configured agent CLI on a loop instruction that
drives ``looptight next`` -> ``verify`` -> commit. Workers coordinate lock-free
through the repo's shared claim store, so no two ever take the same task.

Spawning the agent CLIs (``claude -p`` / ``codex exec`` / ``opencode run``) uses
whatever auth they are logged in with: on a subscription login the swarm runs on
subscription usage, not API credits.

Side effects (git, process spawn) are injected so the orchestration is fully
testable offline; the defaults do the real thing.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

GitFn = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]
SpawnFn = Callable[[list[str], Path, dict[str, str]], None]

# One agentic session per worker, on the CLI's existing (subscription) auth.
_AGENT_ARGV: dict[str, Callable[[str], list[str]]] = {
    "claude": lambda prompt: ["claude", "-p", prompt],
    "codex": lambda prompt: ["codex", "exec", prompt],
    "opencode": lambda prompt: ["opencode", "run", prompt],
}

#: The contract each worker session follows.
WORKER_PROMPT = (
    "You are one worker in a looptight swarm. Loop until the work is done: run "
    "`looptight next` — it prints exactly one grounded task, or `NO_WORK`. If it "
    "prints `NO_WORK`, stop. Otherwise implement exactly that task, then run "
    "`looptight verify`; if it passes, commit with a conventional-commit message; "
    "if it fails, fix and re-verify. Then run `looptight next` again. Coordinate "
    "through looptight's claims — never touch a task another worker holds. Work "
    "one task at a time and keep each change minimal."
)


@dataclass(frozen=True)
class WorkerSpec:
    """A single planned swarm worker. Pure data; no side effects."""

    index: int
    worktree: Path
    branch: str
    session_id: str
    argv: tuple[str, ...]  # the agent command to run inside the worktree

    @property
    def env(self) -> dict[str, str]:
        """Env that pins this worker's distinct claim identity."""
        return {"LOOPTIGHT_SESSION_ID": self.session_id}


@dataclass(frozen=True)
class SwarmResult:
    launched: tuple[WorkerSpec, ...]
    errors: tuple[str, ...] = ()


def _default_base_dir(repo: Path) -> Path:
    repo = repo.resolve()
    return repo.parent / f"{repo.name}-swarm"


def plan_swarm(
    repo: Path, workers: int, agent: str, *, base_dir: Path | None = None
) -> list[WorkerSpec]:
    """Plan ``workers`` isolated worker specs. Pure — creates nothing."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if agent not in _AGENT_ARGV:
        known = ", ".join(sorted(_AGENT_ARGV))
        raise ValueError(f"unknown agent '{agent}'. known agents: {known}")
    base = (base_dir or _default_base_dir(repo)).resolve()
    build = _AGENT_ARGV[agent]
    return [
        WorkerSpec(
            index=i,
            worktree=base / f"w{i}",
            branch=f"looptight/swarm/w{i}",
            session_id=f"swarm-w{i}",
            argv=tuple(build(WORKER_PROMPT)),
        )
        for i in range(1, workers + 1)
    ]


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, errors="replace", check=False
    )


def _spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> None:
    """Launch a detached worker, appending its output to a per-worktree log."""
    log = cwd / "looptight-swarm.log"
    with open(log, "ab") as fh:
        subprocess.Popen(  # noqa: S603 — argv is built from a fixed agent table
            argv,
            cwd=str(cwd),
            env={**os.environ, **env},
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def swarm_up(
    repo: Path,
    workers: int,
    agent: str,
    *,
    base_dir: Path | None = None,
    git_fn: GitFn = _git,
    spawn_fn: SpawnFn = _spawn,
) -> SwarmResult:
    """Create a worktree + branch per worker and launch its agent session.

    A worker whose worktree can't be created is recorded in ``errors`` and skipped
    (it is not launched), so a partial failure still starts the rest of the swarm.
    """
    launched: list[WorkerSpec] = []
    errors: list[str] = []
    for spec in plan_swarm(repo, workers, agent, base_dir=base_dir):
        created = git_fn(["worktree", "add", str(spec.worktree), "-b", spec.branch], repo)
        if created.returncode != 0:
            errors.append(f"w{spec.index}: worktree add failed: {created.stderr.strip()}")
            continue
        spawn_fn(list(spec.argv), spec.worktree, spec.env)
        launched.append(spec)
    return SwarmResult(launched=tuple(launched), errors=tuple(errors))


def swarm_down(
    repo: Path, *, base_dir: Path | None = None, git_fn: GitFn = _git
) -> list[str]:
    """Force-remove the swarm's worktrees (they may be dirty). Returns removed paths."""
    base = (base_dir or _default_base_dir(repo)).resolve()
    removed: list[str] = []
    if not base.is_dir():
        return removed
    for child in sorted(base.glob("w*")):
        if git_fn(["worktree", "remove", "--force", str(child)], repo).returncode == 0:
            removed.append(str(child))
    return removed
