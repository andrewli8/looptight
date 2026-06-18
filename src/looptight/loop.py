"""The loop — supply or delegate (B1, B2, B4).

The orchestrator. By default it *supplies* the loop: checkpoint → iterate →
verify → continue, under a hard iteration cap and post-iteration spend threshold. With ``native``
(the ``--native`` flag) and an adapter that ``supports_native_loop``, it instead
*delegates* to the agent's own eval-gated loop (e.g. Claude `/goal`).

Crucially, **both paths run ``verify`` as the contract and reflect on failure**
(principles 2 and 3), so the summary and the learning layer are identical
whichever path ran. Everything the loop touches is injected, so the control flow
is pure and unit-testable without a real agent or network.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from .adapters.base import Adapter
from .budget import BudgetTracker
from .checkpoint import Checkpointer
from .config import Config
from .lessons import LessonStore
from .metacog import Decision, assess, progress_signal
from .reflect import reflect_on_failure
from .types import IterationRecord, RunResult, StopReason, VerifyResult
from .verify import run_verify

VerifyFn = Callable[[str, Path], VerifyResult]
ReflectFn = Callable[[Adapter, str, VerifyResult, Path], "object"]
ProgressFn = Callable[[IterationRecord], None]


def _continuation_context(verify: VerifyResult) -> str:
    """What we feed back into the next iteration (B2 persistence)."""
    return (
        f"The verification still reports {verify.short()}. Output below — address "
        f"the specific failures, do not paper over them:\n\n{verify.output[-3000:]}"
    )


def run_loop(
    goal: str,
    adapter: Adapter,
    config: Config,
    workdir: Path,
    *,
    native: bool = False,
    verify_fn: VerifyFn = run_verify,
    reflect_fn: ReflectFn = reflect_on_failure,
    checkpointer: Checkpointer | None = None,
    store: LessonStore | None = None,
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
        reflect_fn=reflect_fn,
        checkpointer=checkpointer,
        store=store,
        on_iteration=on_iteration,
    )


def _supply_loop(goal, adapter, config, workdir, *, verify_fn, reflect_fn, checkpointer, store, on_iteration) -> RunResult:
    budget = BudgetTracker(max_iterations=config.max_iterations, budget_usd=config.budget_usd)
    records: list[IterationRecord] = []
    progress: list[float | None] = []
    context = ""
    stop = StopReason.ITERATION_CAP
    error: str | None = None

    for _ in range(config.max_iterations):
        number = budget.start_iteration()
        snapshot = checkpointer.snapshot()

        iteration = adapter.run_iteration(goal, context, workdir)
        budget.add_cost(iteration.cost_usd)

        if not iteration.ok:
            stop = StopReason.ERROR
            error = iteration.error or iteration.transcript or "coding agent failed"
            break

        verify = verify_fn(config.verify, workdir)
        record = IterationRecord(number=number, verify=verify, cost_usd=iteration.cost_usd, checkpoint=snapshot)
        records.append(record)
        if on_iteration:
            on_iteration(record)

        if verify.passed:
            stop = StopReason.SUCCESS
            break
        if budget.over_budget():
            stop = StopReason.BUDGET_EXCEEDED
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
        total_cost_usd=budget.spent_usd,
        diffstat=checkpointer.diffstat(),
        error=error,
    )
    return _maybe_reflect(result, adapter, config, workdir, reflect_fn, store)


def _delegate_loop(goal, adapter, config, workdir, *, verify_fn, reflect_fn, checkpointer, store, on_iteration) -> RunResult:
    """Hand off to the agent's native loop, then verify once as the contract."""
    checkpointer.snapshot()
    iteration = adapter.drive_native_loop(
        goal, config.verify, config.max_iterations, config.budget_usd, workdir
    )
    if not iteration.ok:
        return RunResult(
            goal=goal,
            agent=adapter.name,
            mode="delegate",
            stop_reason=StopReason.ERROR,
            total_cost_usd=iteration.cost_usd,
            diffstat=checkpointer.diffstat(),
            error=iteration.error or iteration.transcript or "coding agent failed",
        )
    verify = verify_fn(config.verify, workdir)
    record = IterationRecord(number=1, verify=verify, cost_usd=iteration.cost_usd)
    if on_iteration:
        on_iteration(record)

    stop = StopReason.SUCCESS if verify.passed else StopReason.ITERATION_CAP
    result = RunResult(
        goal=goal,
        agent=adapter.name,
        mode="delegate",
        stop_reason=stop,
        iterations=(record,),
        total_cost_usd=iteration.cost_usd,
        diffstat=checkpointer.diffstat(),
    )
    return _maybe_reflect(result, adapter, config, workdir, reflect_fn, store)


def _maybe_reflect(result, adapter, config, workdir, reflect_fn, store) -> RunResult:
    """Write a lesson if the run hit (and possibly recovered from) a failure (C1)."""
    if not config.reflect or store is None:
        return result
    failures = [record for record in result.iterations if not record.verify.passed]
    if not failures:
        return result

    lesson = reflect_fn(adapter, result.goal, failures[-1].verify, workdir)
    if lesson is None:
        return result
    store.add(lesson)  # dedupe handled by the store (C4)
    return result.with_lesson(lesson)
