"""Deterministic manager for isolated headless agent workers."""

from __future__ import annotations

import concurrent.futures
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .adapters import get_adapter
from .config import Config, load_config
from .console import Console
from .detect import detect_agent, detect_verify
from .loop import run_loop
from .tasks import next_task
from .types import StopReason
from .verify import run_verify

MAX_WORKERS = 50


@dataclass
class Worker:
    number: int
    task: dict[str, str | None]
    branch: str
    worktree: Path
    base: str
    status: str = "ready"
    error: str | None = None


@dataclass(frozen=True)
class SwarmResult:
    workers: tuple[Worker, ...]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(worker.status == "merged" for worker in self.workers)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def _git_clean(root: Path) -> bool:
    status = _git(root, "status", "--porcelain")
    return status.returncode == 0 and not status.stdout.strip()


def _prepare_workers(root: Path, count: int) -> tuple[list[Worker], str | None]:
    common = _git(root, "rev-parse", "--git-common-dir")
    head = _git(root, "rev-parse", "HEAD")
    if common.returncode != 0 or head.returncode != 0:
        return [], "swarm requires a Git repository with at least one commit"
    common_dir = Path(common.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    run_id = secrets.token_hex(5)
    parent = common_dir / "looptight" / "swarm" / run_id
    parent.mkdir(parents=True, exist_ok=True)

    workers: list[Worker] = []
    for number in range(1, count + 1):
        branch = f"looptight/swarm/{run_id}/{number}"
        worktree = parent / str(number)
        added = _git(root, "worktree", "add", "-q", "--detach", str(worktree), head.stdout.strip())
        if added.returncode != 0:
            return workers, added.stderr.strip() or "could not create worker worktree"
        decision = next_task(worktree)
        if decision.status == "no_work":
            _git(root, "worktree", "remove", str(worktree))
            break
        if decision.status != "task" or decision.task is None:
            return workers, decision.error or "could not claim worker task"
        switched = _git(worktree, "switch", "-q", "-c", branch)
        if switched.returncode != 0:
            return workers, switched.stderr.strip() or "could not create worker branch"
        workers.append(Worker(number, decision.task, branch, worktree, head.stdout.strip()))
    return workers, None


def _run_worker(worker: Worker, agent: str, config: Config) -> Worker:
    result = run_loop(
        str(worker.task["goal"]),
        get_adapter(agent),
        config,
        worker.worktree,
        native=False,
    )
    if result.stop_reason is not StopReason.SUCCESS:
        worker.status = "failed"
        worker.error = result.error or result.stop_reason.value
        return worker

    status = _git(worker.worktree, "status", "--porcelain")
    if status.returncode != 0:
        worker.status = "failed"
        worker.error = status.stderr.strip() or "could not inspect worker changes"
        return worker
    if status.stdout.strip():
        added = _git(worker.worktree, "add", "-A")
        committed = _git(
            worker.worktree,
            "commit",
            "-m",
            f"looptight: {worker.task['id']} {worker.task['source']}",
        )
        if added.returncode != 0 or committed.returncode != 0:
            worker.status = "failed"
            worker.error = committed.stderr.strip() or added.stderr.strip() or "worker commit failed"
            return worker
    else:
        head = _git(worker.worktree, "rev-parse", "HEAD")
        if head.returncode != 0 or head.stdout.strip() == worker.base:
            worker.status = "failed"
            worker.error = "agent produced no changes"
            return worker
    worker.status = "verified"
    return worker


def _integrate(root: Path, worker: Worker, verify: str) -> None:
    if worker.status != "verified":
        return
    merged = _git(root, "merge", "--no-commit", "--no-ff", worker.branch)
    if merged.returncode != 0:
        _git(root, "merge", "--abort")
        worker.status = "conflict"
        worker.error = merged.stderr.strip() or "merge conflict"
        return
    verdict = run_verify(verify, root)
    if not verdict.passed:
        _git(root, "merge", "--abort")
        worker.status = "failed"
        worker.error = f"integration verify: {verdict.status}: {verdict.output[-500:]}"
        return
    commit = _git(root, "commit", "-m", f"merge: looptight swarm task {worker.task['id']}")
    if commit.returncode != 0:
        _git(root, "merge", "--abort")
        worker.status = "failed"
        worker.error = commit.stderr.strip() or "integration commit failed"
        return
    worker.status = "merged"
    _git(root, "worktree", "remove", str(worker.worktree))


def run_swarm(
    root: Path,
    *,
    agent: str,
    config: Config,
    workers: int,
    push: bool = False,
    executor_factory: Callable[..., concurrent.futures.Executor] = concurrent.futures.ThreadPoolExecutor,
) -> SwarmResult:
    """Claim, run, and integrate up to ``workers`` independent tasks."""
    if workers < 1 or workers > MAX_WORKERS:
        return SwarmResult((), f"workers must be between 1 and {MAX_WORKERS}")
    if not config.verify:
        return SwarmResult((), "no verify command configured")
    if not _git_clean(root):
        return SwarmResult((), "swarm requires a clean Git worktree")
    if not get_adapter(agent).is_available():
        return SwarmResult((), f"{agent} is not available on PATH")

    prepared, error = _prepare_workers(root, workers)
    if error:
        return SwarmResult(tuple(prepared), error)
    if not prepared:
        return SwarmResult(())

    with executor_factory(max_workers=len(prepared)) as executor:
        futures = {
            executor.submit(_run_worker, worker, agent, config): worker
            for worker in prepared
        }
        completed: list[Worker] = []
        for future, worker in futures.items():
            try:
                completed.append(future.result())
            except Exception as exc:  # provider/runtime isolation boundary
                worker.status = "failed"
                worker.error = f"worker crashed: {exc}"
                completed.append(worker)
    for worker in sorted(completed, key=lambda item: item.number):
        _integrate(root, worker, config.verify)
    if push and any(worker.status == "merged" for worker in completed):
        pushed = _git(root, "push")
        if pushed.returncode != 0:
            return SwarmResult(
                tuple(completed), pushed.stderr.strip() or "could not push integrated swarm commits"
            )
    return SwarmResult(tuple(completed))


def cmd_swarm(args, console: Console) -> int:
    """CLI boundary for the explicit headless swarm manager."""
    if not args.headless:
        console.print("[red]swarm launches agent child processes.[/red] Pass --headless explicitly.")
        return 2
    if args.workers > MAX_WORKERS:
        console.print(f"[red]workers must be between 1 and {MAX_WORKERS}[/red]")
        return 2
    config = load_config().merged(
        agent=args.agent,
        verify=args.verify,
        max_iterations=args.max_iterations,
    )
    agent = config.agent or detect_agent()
    if not agent:
        console.print("[red]No coding agent found on PATH.[/red]")
        return 2
    if not config.verify:
        config = config.merged(verify=detect_verify(Path.cwd()))
    if not config.verify:
        console.print("[red]No verify command.[/red] Configure one before starting a swarm.")
        return 2
    result = run_swarm(
        Path.cwd(), agent=agent, config=config, workers=args.workers, push=args.push
    )
    if result.error:
        console.print(f"[red]swarm error:[/red] {result.error}")
    if not result.workers and not result.error:
        console.print("NO_WORK")
        return 0
    for worker in result.workers:
        detail = f": {worker.error}" if worker.error else ""
        console.print(f"worker {worker.number} · {worker.task['id']} · {worker.status}{detail}")
    return 0 if result.passed else 1
