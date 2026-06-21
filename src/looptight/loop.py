"""The loop — supply or delegate (B1, B2, B4).

The orchestrator. By default it *supplies* the loop: checkpoint → iterate →
verify → continue, under a hard iteration cap. With ``native``
(the ``--native`` flag) and an adapter that ``supports_native_loop``, it instead
*delegates* to the agent's own eval-gated loop (e.g. Claude `/goal`).

Crucially, **both paths run ``verify`` as the contract**. Everything the loop
touches is injected, so the control flow is unit-testable without a real agent.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .adapters.base import Adapter
from .checkpoint import Checkpointer
from .config import Config
from .limits import (
    DEFAULT_LIMIT_BACKOFF,
    DEFAULT_LIMIT_MAX_WAIT,
    is_limit_error,
    limit_wait,
    retry_after_from_error,
)
from .metacog import Decision, assess, progress_signal
from .types import IterationRecord, RunResult, StopReason, VerifyResult
from .verify import run_verify

VerifyFn = Callable[[str, Path], VerifyResult]
ProgressFn = Callable[[IterationRecord], None]
SleepFn = Callable[[float], None]


_CONTEXT_OUTPUT_LIMIT = 3000


def _continuation_context(verify: VerifyResult) -> str:
    """What we feed back into the next iteration (B2 persistence)."""
    output = verify.output
    if len(output) > _CONTEXT_OUTPUT_LIMIT:
        dropped = len(output) - _CONTEXT_OUTPUT_LIMIT
        output = f"[...{dropped} earlier characters truncated...]\n{output[-_CONTEXT_OUTPUT_LIMIT:]}"
    return (
        f"The verification still reports {verify.short()}. Output below — address "
        f"the specific failures, do not paper over them:\n\n{output}"
    )


def run_loop(
    goal: str,
    adapter: Adapter,
    config: Config,
    workdir: Path,
    *,
    native: bool = False,
    verify_fn: VerifyFn = run_verify,
    checkpointer: Checkpointer | None = None,
    on_iteration: ProgressFn | None = None,
    resume_on_limit: bool = False,
    limit_backoff_seconds: float = DEFAULT_LIMIT_BACKOFF,
    limit_max_wait_seconds: float = DEFAULT_LIMIT_MAX_WAIT,
    sleep: SleepFn = time.sleep,
) -> RunResult:
    """Run ``goal`` to a verified stop. Returns a normalized RunResult."""
    base = RunResult(goal=goal, agent=adapter.name, mode="supply", stop_reason=StopReason.ERROR)

    if not config.verify:
        return replace(base, stop_reason=StopReason.NO_VERIFY)
    if not adapter.is_available():
        return replace(base, stop_reason=StopReason.AGENT_UNAVAILABLE)

    checkpointer = checkpointer or Checkpointer(workdir)
    use_native = native and adapter.supports_native_loop
    if use_native:
        return _delegate_loop(
            goal, adapter, config, workdir,
            verify_fn=verify_fn, checkpointer=checkpointer, on_iteration=on_iteration,
        )
    return _supply_loop(
        goal, adapter, config, workdir,
        verify_fn=verify_fn, checkpointer=checkpointer, on_iteration=on_iteration,
        resume_on_limit=resume_on_limit,
        limit_backoff_seconds=limit_backoff_seconds,
        limit_max_wait_seconds=limit_max_wait_seconds,
        sleep=sleep,
    )


def _iterate(adapter, goal, context, workdir, *, resume_on_limit, base, cap, sleep):
    """Run one iteration, waiting out a provider usage limit when opted in.

    A limit costs no iteration-cap slot — the agent did no work — so we sleep
    (preferring the provider's named reset, capped) and retry until the provider
    returns a real result. This is the single-agent twin of the swarm's per-round
    back-off, so an unattended ``run`` resumes after a limit instead of stopping.
    """
    attempt = 0
    while True:
        iteration = adapter.run_iteration(goal, context, workdir)
        if not resume_on_limit or iteration.ok or not is_limit_error(iteration.error):
            return iteration
        attempt += 1
        sleep(limit_wait(retry_after_from_error(iteration.error), attempt, base, cap))


def _supply_loop(
    goal, adapter, config, workdir, *, verify_fn, checkpointer, on_iteration,
    resume_on_limit, limit_backoff_seconds, limit_max_wait_seconds, sleep,
) -> RunResult:
    records: list[IterationRecord] = []
    progress: list[float | None] = []
    context = ""
    stop = StopReason.ITERATION_CAP
    error: str | None = None

    for number in range(1, config.max_iterations + 1):
        snapshot = checkpointer.snapshot()

        iteration = _iterate(
            adapter, goal, context, workdir,
            resume_on_limit=resume_on_limit,
            base=limit_backoff_seconds,
            cap=limit_max_wait_seconds,
            sleep=sleep,
        )

        if not iteration.ok:
            stop = StopReason.ERROR
            error = iteration.error or iteration.transcript or "coding agent failed"
            break

        verify = verify_fn(config.verify, workdir)
        record = IterationRecord(number=number, verify=verify, checkpoint=snapshot)
        records.append(record)
        if on_iteration:
            on_iteration(record)

        if verify.passed:
            stop = StopReason.SUCCESS
            break
        # Value-aware stopping: cut a stalled loop short instead of burning the
        # rest of the cap (no-op when config.patience is 0).
        progress.append(progress_signal(verify))
        decision = assess(progress, config.patience)
        if decision is Decision.ESCALATE:
            stop = StopReason.ESCALATED
            break
        if decision is Decision.STOP_NO_PROGRESS:
            stop = StopReason.NO_PROGRESS
            break

        context = _continuation_context(verify)

    result = RunResult(
        goal=goal,
        agent=adapter.name,
        mode="supply",
        stop_reason=stop,
        iterations=tuple(records),
        diffstat=checkpointer.diffstat(),
        error=error,
    )
    return result


def _delegate_loop(goal, adapter, config, workdir, *, verify_fn, checkpointer, on_iteration) -> RunResult:
    """Hand off to the agent's native loop, then verify once as the contract."""
    checkpointer.snapshot()
    iteration = adapter.drive_native_loop(
        goal, config.verify, config.max_iterations, workdir
    )
    if not iteration.ok:
        return RunResult(
            goal=goal,
            agent=adapter.name,
            mode="delegate",
            stop_reason=StopReason.ERROR,
            diffstat=checkpointer.diffstat(),
            error=iteration.error or iteration.transcript or "coding agent failed",
        )
    verify = verify_fn(config.verify, workdir)
    record = IterationRecord(number=1, verify=verify)
    if on_iteration:
        on_iteration(record)

    stop = StopReason.SUCCESS if verify.passed else StopReason.ITERATION_CAP
    result = RunResult(
        goal=goal,
        agent=adapter.name,
        mode="delegate",
        stop_reason=stop,
        iterations=(record,),
        diffstat=checkpointer.diffstat(),
    )
    return result
