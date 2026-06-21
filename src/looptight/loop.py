"""The loop — supply or delegate (B1, B2, B4).

The orchestrator. By default it *supplies* the loop: checkpoint → iterate →
verify → continue, under a hard iteration cap. With ``native``
(the ``--native`` flag) and an adapter that ``supports_native_loop``, it instead
*delegates* to the agent's own eval-gated loop (e.g. Claude `/goal`).

Crucially, **both paths run ``verify`` as the contract**. Everything the loop
touches is injected, so the control flow is unit-testable without a real agent.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from .adapters.base import Adapter
from .checkpoint import Checkpointer
from .config import Config
from .metacog import Decision, assess, progress_signal
from .types import IterationRecord, RunResult, StopReason, VerifyResult
from .verify import run_verify

VerifyFn = Callable[[str, Path], VerifyResult]
ProgressFn = Callable[[IterationRecord], None]


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
) -> RunResult:
    """Run ``goal`` to a verified stop. Returns a normalized RunResult."""
    base = RunResult(goal=goal, agent=adapter.name, mode="supply", stop_reason=StopReason.ERROR)

    if not config.verify:
        return replace(base, stop_reason=StopReason.NO_VERIFY)
    if not adapter.is_available():
        return replace(base, stop_reason=StopReason.AGENT_UNAVAILABLE)

    checkpointer = checkpointer or Checkpointer(workdir)
    use_native = native and adapter.supports_native_loop
    runner = _delegate_loop if use_native else _supply_loop
    return runner(
        goal,
        adapter,
        config,
        workdir,
        verify_fn=verify_fn,
        checkpointer=checkpointer,
        on_iteration=on_iteration,
    )


def _supply_loop(goal, adapter, config, workdir, *, verify_fn, checkpointer, on_iteration) -> RunResult:
    records: list[IterationRecord] = []
    progress: list[float | None] = []
    context = ""
    stop = StopReason.ITERATION_CAP
    error: str | None = None

    for number in range(1, config.max_iterations + 1):
        snapshot = checkpointer.snapshot()

        iteration = adapter.run_iteration(goal, context, workdir)

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
