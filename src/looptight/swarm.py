"""Deterministic manager for isolated headless agent workers."""

from __future__ import annotations

import concurrent.futures
import json
import secrets
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .adapters import get_adapter
from .adapters.base import stop_active_processes
from .config import Config, load_config
from .console import Console
from .detect import detect_agent, detect_verify
from .discovery import Candidate, from_status_next
from .grounding import evidence_refs, strip_anchor_decoration
from .limits import (
    DEFAULT_LIMIT_BACKOFF,
    DEFAULT_LIMIT_MAX_WAIT,
    is_limit_error,
    limit_wait,
    retry_after_from_error,
)
from .coordinator import Coordinator
from .integration_queue import (
    _GIT_IDENTITY,
    _git_env,
    CoordinationTimeout,
    IntegrationLock,
    Integrator,
    Publisher,
    git_common_dir,
)
from .loop import run_loop
from .experience import build_model
from .prompts import PLANNING_GOAL, planning_goal
from .tasks import next_task
from .types import StopReason
from .ui import STATE_SCHEMA_VERSION, write_state
from .verify import run_verify

MAX_WORKERS = 50
DEFAULT_WORKER_TIMEOUT = 3600.0
INTEGRATION_LOCK_TIMEOUT = 300.0
DEFAULT_MAX_IDLE_ROUNDS = 3

# Why a swarm run returned. A supervisor (the daemon) reads this to decide its
# next move without parsing error strings: REASON_IDLE/REASON_NO_WORK are expected
# "nothing to build right now" exits to poll after a back-off, REASON_LIMIT is a
# transient provider cap to wait out, and only REASON_ERROR is a genuine fault.
REASON_OK = "ok"
REASON_NO_WORK = "no_work"
REASON_IDLE = "idle"
REASON_LIMIT = "limit"
REASON_ERROR = "error"
SCHEMA_VERSION = 1


@dataclass
class Worker:
    number: int
    task: dict[str, str | None]
    branch: str
    worktree: Path
    base: str
    status: str = "ready"
    error: str | None = None
    run_id: str | None = None  # coordinator run that holds this worker's lease
    integration_id: str | None = None  # queued integration, set at handoff


@dataclass(frozen=True)
class SwarmResult:
    workers: tuple[Worker, ...]
    error: str | None = None
    pushed: str | None = None
    rounds: int = 1
    plans: int = 0
    resumes: int = 0  # times the continuous run waited out a provider usage limit
    reason: str = REASON_OK  # why the run returned; see REASON_* (read by the daemon)

    @property
    def passed(self) -> bool:
        return self.error is None and all(worker.status == "merged" for worker in self.workers)

    @property
    def status(self) -> str:
        if self.error:
            return "error"
        if not self.workers:
            return "no_work"
        return "pass" if self.passed else "fail"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "command": "swarm",
            "status": self.status,
            "error": self.error,
            "push": self.pushed,
            "rounds": self.rounds,
            "plans": self.plans,
            "resumes": self.resumes,
            "reason": self.reason,
            "workers": [
                {
                    "number": worker.number,
                    "task_id": worker.task["id"] if worker.task else None,
                    "status": worker.status,
                    "error": worker.error,
                    "worktree": str(worker.worktree),
                }
                for worker in self.workers
            ],
        }


@dataclass(frozen=True)
class PlanningResult:
    status: str
    error: str | None = None
    worktree: Path | None = None


def _planned_tasks_are_grounded(root: Path, candidates: list[Candidate]) -> bool:
    for candidate in candidates:
        # Find anchors with the shared parser so the planner's marker tolerance
        # (markdown emphasis, code spans) cannot drift from the grounding gate, as
        # it once did. The planner keeps its own stricter policy below: it also
        # rejects the STATUS file as circular evidence and checks the cited line
        # is within the file, neither of which the gate does.
        refs = evidence_refs(candidate.detail or "")
        if not refs:
            return False
        for ref in refs:
            reference = strip_anchor_decoration(ref)
            path_text, separator, line_text = reference.rpartition(":")
            if not separator or not line_text.isdigit():
                path_text, line_text = reference, ""
            path = Path(path_text)
            if path.is_absolute() or ".." in path.parts or path == Path("docs/STATUS.md"):
                return False
            evidence = root / path
            if not evidence.is_file():
                return False
            if line_text:
                lines = evidence.read_text(encoding="utf-8", errors="ignore").splitlines()
                if int(line_text) < 1 or int(line_text) > len(lines):
                    return False
    return True


def _publish_state(
    root: Path,
    workers: list[Worker] | tuple[Worker, ...],
    manager_status: str,
) -> None:
    state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "manager": {"status": manager_status},
        "tasks": [
            {
                "id": worker.task["id"],
                "goal": worker.task["goal"],
                "source": worker.task["source"],
                "status": worker.status,
            }
            for worker in workers
        ],
        "workers": [
            {
                "number": worker.number,
                "task_id": worker.task["id"],
                "status": worker.status,
                "error": worker.error,
            }
            for worker in workers
        ],
    }
    try:
        write_state(root, state)
    except OSError:
        # Observability is best-effort and must never disrupt orchestration.
        pass


def _result(root: Path, result: SwarmResult) -> SwarmResult:
    _publish_state(root, result.workers, result.status)
    return result


# The deterministic committer identity for looptight's automated commits/merges is
# defined once in integration_queue and imported above, so the swarm and the
# integration queue cannot drift out of sync.


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *_GIT_IDENTITY, *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def _git_clean(root: Path) -> bool:
    status = _git(root, "status", "--porcelain")
    return status.returncode == 0 and not status.stdout.strip()


def _remove_worker_worktree(root: Path, worktree: Path) -> subprocess.CompletedProcess[str]:
    # --force: the worktree is always disposable here (nothing claimed, or the
    # verified result is already merged), and plain `remove` refuses a worktree
    # that holds untracked files, which would otherwise leak it on disk.
    removed = _git(root, "worktree", "remove", "--force", str(worktree))
    if removed.returncode == 0:
        try:
            worktree.parent.rmdir()
        except OSError:
            pass
    return removed


def _task_paths(root: Path, task: dict[str, str | None]) -> set[str]:
    """Return grounded paths that may be changed while completing ``task``."""
    paths: set[str] = set()
    # The evidence field carries markdown-decorated anchors (`` `path:line` ``);
    # find and normalize them through the shared parser so the bare file lands in
    # the scope set, not a backtick-wrapped non-path.
    references = [task.get("location"), *evidence_refs(task.get("evidence") or "")]
    for reference in references:
        if not reference:
            continue
        reference = strip_anchor_decoration(reference)
        path_text, separator, line_text = reference.rpartition(":")
        if not separator or not line_text.isdigit():
            path_text = reference
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts:
            continue
        relative = path.as_posix()
        paths.add(relative)
        if len(path.parts) >= 2 and path.parts[0] == "src" and path.suffix == ".py":
            counterpart = Path("tests") / f"test_{path.stem}.py"
            if (root / counterpart).is_file():
                paths.add(counterpart.as_posix())
    return paths


def _worker_changed_paths(worker: Worker) -> tuple[list[str] | None, str | None]:
    changed = _git(worker.worktree, "diff", "--name-only", "-z", worker.base, "--")
    untracked = _git(
        worker.worktree, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if changed.returncode != 0 or untracked.returncode != 0:
        error = changed.stderr.strip() or untracked.stderr.strip()
        return None, error or "could not inspect worker changes"
    paths = sorted(set((changed.stdout + untracked.stdout).rstrip("\0").split("\0")))
    return ([path for path in paths if path], None)


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
        # A distinct run id per worker so the coordinator leases each a distinct
        # task, and so the manager can later enqueue the worker's own lease.
        worker_run_id = f"{run_id}-w{number}"
        decision = next_task(worktree, run_id=worker_run_id)
        if decision.status == "no_work":
            _remove_worker_worktree(root, worktree)
            break
        if decision.status != "task" or decision.task is None:
            _remove_worker_worktree(root, worktree)
            return workers, decision.error or "could not claim worker task"
        switched = _git(worktree, "switch", "-q", "-c", branch)
        if switched.returncode != 0:
            _remove_worker_worktree(root, worktree)
            return workers, switched.stderr.strip() or "could not create worker branch"
        workers.append(
            Worker(number, decision.task, branch, worktree, head.stdout.strip(), run_id=worker_run_id)
        )
    return workers, None


def _run_worker(worker: Worker, agent: str, config: Config, worker_timeout: float) -> Worker:
    adapter = get_adapter(agent)
    adapter.worker_timeout_s = worker_timeout
    result = run_loop(
        str(worker.task["goal"]),
        adapter,
        config,
        worker.worktree,
        native=False,
    )
    if result.stop_reason is not StopReason.SUCCESS:
        worker.error = result.error or result.stop_reason.value
        if is_limit_error(worker.error):
            worker.status = "limited"
        elif result.returncode == 124:
            worker.status = "timeout"
        else:
            worker.status = "failed"
        return worker

    changed_paths, error = _worker_changed_paths(worker)
    if changed_paths is None:
        worker.status = "failed"
        worker.error = error
        return worker
    outside_scope = sorted(set(changed_paths) - _task_paths(worker.worktree, worker.task))
    if outside_scope:
        worker.status = "failed"
        worker.error = "worker changed files outside task scope: " + ", ".join(outside_scope)
        return worker

    status = _git(worker.worktree, "status", "--porcelain")
    if status.returncode != 0:
        worker.status = "failed"
        worker.error = status.stderr.strip() or "could not inspect worker changes"
        return worker
    if status.stdout.strip():
        added = _git(worker.worktree, "add", "-A", "--", *changed_paths)
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


def _integrate(root: Path, worker: Worker, verify: str) -> None:  # pragma: no cover
    # The locked direct-merge fallback, used only when no coordinator is available. A swarm
    # requires a clean Git worktree, so `Coordinator.open` is never None here and the durable
    # Integrator path is always taken; this body is unreachable in normal runs (its sole caller
    # at `_integrate_via_queue` is likewise `# pragma: no cover`). Kept as a defensive fallback.
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
    _remove_worker_worktree(root, worker.worktree)


_INTEGRATION_STATUS = {
    "complete": "merged",
    "conflict": "conflict",
    "failed": "failed",
    "superseded": "failed",
}


def _publish_via_queue(root: Path, workers: list[Worker]) -> str:
    """Publish merged integrations to the remote idempotently via the durable queue.

    Each merged worker's completed integration is enqueued and drained by the
    `Publisher`, which fetches first and finalizes without a second push when the
    remote already has the result, pushing only the exact result SHA (never force).
    """
    coordinator = Coordinator.open(root)
    if coordinator is None:  # pragma: no cover - swarm always runs inside Git
        return "pushed" if _git(root, "push").returncode == 0 else "failed"
    try:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        remote = _git(root, "config", f"branch.{branch}.remote").stdout.strip() or "origin"
        remote_ref = f"refs/heads/{branch}"
        enqueued = [
            coordinator.enqueue_publication(worker.integration_id, remote, remote_ref)
            for worker in workers
            if worker.status == "merged" and worker.integration_id
        ]
        Publisher(coordinator, lock_timeout_s=INTEGRATION_LOCK_TIMEOUT).reconcile(root)
        if all(coordinator.publication(pub_id).state == "complete" for pub_id in enqueued):
            return "pushed"
        return "failed"
    finally:
        coordinator.close()


def _reconcile_pending(root: Path, verify: str) -> None:
    """Finalize any integration a crashed prior run left in `integrating` state."""
    coordinator = Coordinator.open(root)
    if coordinator is None:  # pragma: no cover - swarm always runs inside Git
        return
    try:
        Integrator(coordinator, lock_timeout_s=INTEGRATION_LOCK_TIMEOUT).reconcile(root, verify)
    finally:
        coordinator.close()


def _integrate_via_queue(root: Path, workers: list[Worker], verify: str) -> None:
    """Hand verified workers to the durable coordinator queue and drain it.

    Each verified worker's committed branch is enqueued (fenced to its lease) and
    integrated one-at-a-time by the Integrator (merge in a coordinator worktree,
    verify, CAS-advance the target ref). The primary worktree, kept clean by the
    swarm, is then synced to the advanced ref. Falls back to a locked direct merge
    only when no coordinator is available.
    """
    coordinator = Coordinator.open(root)
    if coordinator is None:  # pragma: no cover - swarm always runs inside Git
        with IntegrationLock.acquire(git_common_dir(root), timeout_s=INTEGRATION_LOCK_TIMEOUT):
            for worker in workers:
                _integrate(root, worker, verify)
        return
    try:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        target_ref = f"refs/heads/{branch}"
        queued: list[Worker] = []
        for worker in workers:
            if worker.status != "verified":
                continue
            lease = coordinator.lease_for(str(worker.task["id"]), worker.run_id or "")
            if lease is None:
                worker.status = "failed"
                worker.error = "lost task lease before integration"
                continue
            candidate_sha = _git(worker.worktree, "rev-parse", "HEAD").stdout.strip()
            worker.integration_id = coordinator.enqueue_integration(lease, target_ref, candidate_sha)
            queued.append(worker)

        integrator = Integrator(coordinator, lock_timeout_s=INTEGRATION_LOCK_TIMEOUT)
        outcomes = {}
        while True:
            outcome = integrator.run_next(root, verify)
            if outcome is None:
                break
            outcomes[outcome.id] = outcome

        integrated = False
        for worker in queued:
            outcome = outcomes.get(worker.integration_id)
            if outcome is None:
                worker.status = "failed"
                worker.error = "integration did not run"
                continue
            worker.status = _INTEGRATION_STATUS.get(outcome.status, "failed")
            if outcome.status == "complete":
                integrated = True
                _remove_worker_worktree(root, worker.worktree)
            else:
                worker.error = outcome.error
        if integrated:
            # The swarm requires a clean primary worktree, so fast-forwarding it to
            # the advanced ref is safe and keeps it consistent with main.
            _git(root, "reset", "--hard", target_ref)
    finally:
        coordinator.close()


def _planner_worktree(root: Path) -> tuple[Path | None, str | None, str | None]:
    common = _git(root, "rev-parse", "--git-common-dir")
    head = _git(root, "rev-parse", "HEAD")
    if common.returncode != 0 or head.returncode != 0:
        return None, None, "continuous planning requires a Git repository with at least one commit"
    common_dir = Path(common.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    worktree = common_dir / "looptight" / "planner" / secrets.token_hex(5)
    added = _git(root, "worktree", "add", "-q", "--detach", str(worktree), head.stdout.strip())
    if added.returncode != 0:
        return None, None, added.stderr.strip() or "could not create planner worktree"
    return worktree, head.stdout.strip(), None


def plan_next_tasks(
    root: Path,
    *,
    agent: str,
    verify: str,
    timeout: float = DEFAULT_WORKER_TIMEOUT,
    push: bool = False,
) -> PlanningResult:
    """Ask the provider to create a bounded grounded plan in an isolated worktree."""
    worktree, base, error = _planner_worktree(root)
    if error or worktree is None or base is None:
        return PlanningResult("failed", error)
    adapter = get_adapter(agent)
    adapter.worker_timeout_s = timeout
    coordinator = Coordinator.open(root)
    goal = PLANNING_GOAL
    if coordinator is not None:
        try:
            model = build_model(root, "HEAD", coordinator, cooldown_s=24 * 3600.0)
            goal = planning_goal(model)
        finally:
            coordinator.close()
    outcome = adapter.run_iteration(goal, "", worktree)
    status = _git(worktree, "status", "--porcelain")
    if status.returncode != 0:
        return PlanningResult(
            "failed", status.stderr.strip() or "could not inspect planner changes", worktree
        )
    diff = _git(worktree, "diff", "--name-only", base)
    if diff.returncode != 0:
        return PlanningResult(
            "failed", diff.stderr.strip() or "could not inspect planner diff", worktree
        )
    changed = sorted(
        set(diff.stdout.splitlines())
        | {line[3:] for line in status.stdout.splitlines() if len(line) > 3}
    )
    if not changed and outcome.ok:
        _git(root, "worktree", "remove", str(worktree))
        return PlanningResult("no_work")
    if not outcome.ok:
        return PlanningResult("failed", outcome.error or "planner provider failed", worktree)
    if changed != ["docs/STATUS.md"]:
        return PlanningResult(
            "failed",
            "planner may change only docs/STATUS.md; changed: " + ", ".join(changed),
            worktree,
        )
    candidates = from_status_next(worktree)
    if not 1 <= len(candidates) <= 6 or not _planned_tasks_are_grounded(worktree, candidates):
        return PlanningResult(
            "failed",
            "planner must produce 1-6 tasks with valid Evidence paths and Acceptance clauses",
            worktree,
        )
    verdict = run_verify(verify, worktree)
    if not verdict.passed:
        return PlanningResult(
            "failed", f"planner verify: {verdict.status}: {verdict.output[-500:]}", worktree
        )
    if status.stdout.strip():
        added = _git(worktree, "add", "docs/STATUS.md")
        committed = _git(worktree, "commit", "-m", "plan: refresh looptight swarm tasks")
        if added.returncode != 0 or committed.returncode != 0:
            return PlanningResult(
                "failed",
                committed.stderr.strip() or added.stderr.strip() or "planner commit failed",
                worktree,
            )
    head = _git(worktree, "rev-parse", "HEAD")
    if head.returncode != 0:
        return PlanningResult(
            "failed", head.stderr.strip() or "could not resolve planner commit", worktree
        )
    merged = _git(root, "merge", "--no-commit", "--no-ff", head.stdout.strip())
    if merged.returncode != 0:
        _git(root, "merge", "--abort")
        return PlanningResult(
            "failed", merged.stderr.strip() or "planner integration conflict", worktree
        )
    integrated = run_verify(verify, root)
    if not integrated.passed:
        _git(root, "merge", "--abort")
        return PlanningResult(
            "failed",
            f"planner integration verify: {integrated.status}: {integrated.output[-500:]}",
            worktree,
        )
    commit = _git(root, "commit", "-m", "merge: refresh continuous swarm plan")
    if commit.returncode != 0:
        _git(root, "merge", "--abort")
        return PlanningResult(
            "failed", commit.stderr.strip() or "planner integration commit failed", worktree
        )
    _git(root, "worktree", "remove", str(worktree))
    if push:
        pushed = _git(root, "push")
        if pushed.returncode != 0:
            return PlanningResult("failed", pushed.stderr.strip() or "could not push planner commit")
    return PlanningResult("planned")


def run_swarm(
    root: Path,
    *,
    agent: str,
    config: Config,
    workers: int,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    push: bool = False,
    executor_factory: Callable[..., concurrent.futures.Executor] = concurrent.futures.ThreadPoolExecutor,
) -> SwarmResult:
    """Claim, run, and integrate up to ``workers`` independent tasks."""
    if workers < 1 or workers > MAX_WORKERS:
        return _result(root, SwarmResult((), f"workers must be between 1 and {MAX_WORKERS}"))
    if not config.verify:
        return _result(root, SwarmResult((), "no verify command configured"))
    if not _git_clean(root):
        return _result(root, SwarmResult((), "swarm requires a clean Git worktree"))
    if not get_adapter(agent).is_available():
        return _result(root, SwarmResult((), f"{agent} is not available on PATH"))

    # Recover any integration a crashed prior run left mid-flight before new work.
    _reconcile_pending(root, config.verify)

    prepared, error = _prepare_workers(root, workers)
    if error:
        return _result(root, SwarmResult(tuple(prepared), error))
    if not prepared:
        return _result(root, SwarmResult(()))
    _publish_state(root, prepared, "running")

    with executor_factory(max_workers=len(prepared)) as executor:
        futures = {}
        for worker in prepared:
            worker.status = "running"
            future = executor.submit(_run_worker, worker, agent, config, worker_timeout)
            futures[future] = worker
        _publish_state(root, prepared, "running")
        completed: list[Worker] = []
        try:
            for future in concurrent.futures.as_completed(futures):
                worker = futures[future]
                try:
                    completed.append(future.result())
                except Exception as exc:  # provider/runtime isolation boundary
                    worker.status = "failed"
                    worker.error = f"worker crashed: {exc}"
                    completed.append(worker)
                _publish_state(root, prepared, "running")
        except KeyboardInterrupt:
            stop_active_processes()
            for worker in prepared:
                if worker.status in {"ready", "running"}:
                    worker.status = "interrupted"
                    worker.error = "interrupted"
            _publish_state(root, prepared, "interrupted")
            for future in futures:
                future.cancel()
            raise
    completed.sort(key=lambda item: item.number)
    try:
        _integrate_via_queue(root, completed, config.verify)
    except CoordinationTimeout as exc:
        return _result(root, SwarmResult(tuple(completed), str(exc)))
    _publish_state(root, prepared, "running")
    if push and any(worker.status == "merged" for worker in completed):
        if _publish_via_queue(root, completed) != "pushed":
            return _result(root, SwarmResult(
                tuple(completed), "could not publish integrated swarm commits", pushed="failed",
            ))
        return _result(root, SwarmResult(tuple(completed), pushed="pushed"))
    return _result(root, SwarmResult(tuple(completed)))


def run_continuous_swarm(
    root: Path,
    *,
    agent: str,
    config: Config,
    workers: int,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    push: bool = False,
    max_rounds: int = 0,
    resume_on_limit: bool = False,
    limit_backoff_seconds: float = DEFAULT_LIMIT_BACKOFF,
    limit_max_wait_seconds: float = DEFAULT_LIMIT_MAX_WAIT,
    limit_max_resumes: int = 0,
    sleep: Callable[[float], None] = time.sleep,
    generate_ideas: bool = True,
    max_idle_rounds: int = DEFAULT_MAX_IDLE_ROUNDS,
) -> SwarmResult:
    """Repeat verified swarm rounds, planning only when grounded work is exhausted.

    With ``resume_on_limit``, a round (or planning pass) that fails *solely*
    because the provider reported a usage/rate limit is not terminal: the run
    sleeps (preferring the provider's named reset, else exponential back-off
    capped at ``limit_max_wait_seconds``) and resumes. Genuine verify failures and
    crashes still stop the run.

    When ``generate_ideas`` is False (``--no-ideas``), an exhausted queue ends the
    run instead of invoking the planner subagent to propose new grounded tasks.
    """
    completed: list[Worker] = []
    rounds = 0
    plans = 0
    resumes = 0
    limit_attempt = 0
    idle_rounds = 0
    pushed: str | None = None
    while max_rounds == 0 or rounds < max_rounds:
        result = run_swarm(
            root,
            agent=agent,
            config=config,
            workers=workers,
            worker_timeout=worker_timeout,
            push=push,
        )
        rounds += 1
        pushed = result.pushed or pushed
        if result.error:
            completed.extend(result.workers)
            return SwarmResult(
                tuple(completed), result.error, pushed,
                rounds=rounds, plans=plans, resumes=resumes, reason=REASON_ERROR,
            )
        if result.workers and not result.passed:
            non_merged = [w for w in result.workers if w.status != "merged"]
            if resume_on_limit and non_merged and all(w.status == "limited" for w in non_merged):
                # Keep work that already merged this round; the limited workers'
                # tasks stay grounded and are re-claimed on the next round.
                completed.extend(w for w in result.workers if w.status == "merged")
                if limit_max_resumes and limit_attempt >= limit_max_resumes:
                    return SwarmResult(
                        tuple(completed),
                        f"provider usage limit persisted after {limit_max_resumes} resumes",
                        pushed, rounds=rounds, plans=plans, resumes=resumes, reason=REASON_LIMIT,
                    )
                limit_attempt += 1
                named = max((retry_after_from_error(w.error) or 0.0) for w in non_merged)
                sleep(limit_wait(named or None, limit_attempt, limit_backoff_seconds, limit_max_wait_seconds))
                resumes += 1
                continue
            completed.extend(result.workers)
            return SwarmResult(
                tuple(completed), result.error, pushed,
                rounds=rounds, plans=plans, resumes=resumes, reason=REASON_ERROR,
            )
        completed.extend(result.workers)
        if result.workers:
            # Only a productive round resets the limit-resume counter. Resetting it
            # unconditionally let a *persistent planner* usage-limit loop forever: each
            # no-work round cleared the counter before the planner-limit cap below could
            # ever trip, so --limit-max-resumes was ineffective for the planning path.
            limit_attempt = 0
            idle_rounds = 0  # merged work this round resets the no-progress counter
            continue
        if max_rounds and rounds >= max_rounds:
            return SwarmResult(tuple(completed), pushed=pushed, rounds=rounds, plans=plans, resumes=resumes)
        if not generate_ideas:
            return SwarmResult(
                tuple(completed), pushed=pushed,
                rounds=rounds, plans=plans, resumes=resumes, reason=REASON_NO_WORK,
            )
        planning = plan_next_tasks(
            root,
            agent=agent,
            verify=config.verify or "",
            timeout=worker_timeout,
            push=push,
        )
        if planning.status == "planned":
            plans += 1
            idle_rounds += 1
            if max_idle_rounds and idle_rounds >= max_idle_rounds:
                return SwarmResult(
                    tuple(completed),
                    f"continuous swarm made no merged progress across {max_idle_rounds} planning rounds",
                    pushed, rounds=rounds, plans=plans, resumes=resumes, reason=REASON_IDLE,
                )
            pushed = "pushed" if push else pushed
            continue
        if planning.status == "no_work":
            return SwarmResult(
                tuple(completed), pushed=pushed,
                rounds=rounds, plans=plans, resumes=resumes, reason=REASON_NO_WORK,
            )
        if resume_on_limit and is_limit_error(planning.error):
            if limit_max_resumes and limit_attempt >= limit_max_resumes:
                return SwarmResult(
                    tuple(completed),
                    f"provider usage limit persisted after {limit_max_resumes} resumes",
                    pushed, rounds=rounds, plans=plans, resumes=resumes, reason=REASON_LIMIT,
                )
            limit_attempt += 1
            named = retry_after_from_error(planning.error)
            sleep(limit_wait(named, limit_attempt, limit_backoff_seconds, limit_max_wait_seconds))
            resumes += 1
            continue
        retained = f"; planner worktree retained: {planning.worktree}" if planning.worktree else ""
        return SwarmResult(
            tuple(completed),
            (planning.error or "planner failed") + retained,
            pushed,
            rounds=rounds,
            plans=plans,
            resumes=resumes,
            reason=REASON_ERROR,
        )
    return SwarmResult(tuple(completed), pushed=pushed, rounds=rounds, plans=plans, resumes=resumes)


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
        model=args.model,
        verify=args.verify,
        max_iterations=args.max_iterations,
        idea_generation=False if args.no_ideas else None,
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
    if args.push and config.no_direct_push:
        console.print("[red]direct push disabled by policy.[/red] Remove --push or update .looptight.toml.")
        return 2
    runner = run_continuous_swarm if args.continuous else run_swarm
    options = {
        "agent": agent,
        "config": config,
        "workers": args.workers,
        "worker_timeout": args.worker_timeout,
        "push": args.push,
    }
    if args.continuous:
        options["max_rounds"] = args.max_rounds
        options["resume_on_limit"] = args.resume_on_limit
        options["limit_backoff_seconds"] = args.limit_backoff_seconds
        options["limit_max_wait_seconds"] = args.limit_max_wait_seconds
        options["generate_ideas"] = config.idea_generation
    if not args.json:
        console.print(
            _swarm_banner(
                args.workers,
                agent,
                config.verify,
                args.continuous,
                args.max_rounds,
                args.continuous and args.resume_on_limit,
            )
        )
    result = runner(Path.cwd(), **options)
    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
        return 0 if result.passed else 1
    if result.error:
        console.print(f"[red]swarm error:[/red] {result.error}")
    if args.continuous:
        console.print(
            f"continuous · {result.rounds} rounds · {result.plans} plans · {result.resumes} resumes"
        )
    if not result.workers and not result.error:
        console.print("NO_WORK")
        return 0
    for worker in result.workers:
        detail = f": {worker.error}" if worker.error else ""
        console.print(f"worker {worker.number} · {worker.task['id']} · {worker.status}{detail}")
        if worker.status in {"failed", "timeout", "conflict"}:
            console.print(f"  worktree retained for recovery: {worker.worktree}")
    counts = Counter(worker.status for worker in result.workers)
    console.print("explanation: verified workers integrate one at a time")
    console.print(f"integration: merged {counts['merged']}")
    console.print(
        "next: inspect retained worktrees for failures or continue with `looptight next --json`"
    )
    console.print("recovery: stale leases requeue when abandoned runs are reaped")
    console.print("recovery: pending integrations are reconciled before claiming new work")
    console.print("recovery: rejected pushes stay failed and are never force-pushed")
    console.print(_swarm_tally(result.workers))
    return 0 if result.passed else 1


def _swarm_banner(workers, agent, verify, continuous, max_rounds, resume_on_limit=False) -> str:
    """One-line start banner naming what the swarm is about to run."""
    if continuous:
        # max_rounds == 0 means run until no work/failure/interruption (cli.py), so
        # naming a "max 0 rounds" cap is misleading — the run is unbounded.
        plan = "continuous · unbounded rounds" if max_rounds == 0 else f"continuous · max {max_rounds} rounds"
    else:
        plan = "single round"
    if resume_on_limit:
        plan += " · resume-on-limit"
    return f"swarm · {workers} workers · agent {agent} · verify {verify} · {plan}"


def _swarm_tally(workers) -> str:
    """One-line outcome tally counting workers by terminal status."""
    counts = Counter(worker.status for worker in workers)
    preferred = ["merged", "failed", "timeout", "conflict"]
    ordered = preferred + sorted(set(counts) - set(preferred))
    parts = [f"{status} {counts[status]}" for status in ordered if counts[status]]
    return f"{len(workers)} workers · " + " · ".join(parts)
