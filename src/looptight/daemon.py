"""A supervisor that keeps a continuous swarm running indefinitely.

``run_continuous_swarm`` is designed to *return* — when the grounded backlog is
exhausted, when a usage limit persists, or on a fault. That is correct for a
bounded ``swarm --continuous`` invocation, but it is also why the loop does not
run on its own: nothing restarts it. The daemon is the missing piece. It runs the
continuous swarm in a cycle and, reading the structured ``SwarmResult.reason``,
decides how long to wait before the next cycle:

* merged progress  -> loop again immediately (drain the backlog fast),
* nothing to build -> poll again after ``idle_sleep_seconds`` (token-respectful),
* a genuine fault  -> exponential, capped back-off so a broken state self-heals
  without hammering, and a persistent failure stays observable.

It runs forever unless ``max_cycles`` is set (bounded runs, tests) or
``should_stop`` reports a shutdown signal. Crashes inside a cycle are absorbed as
faults so a single bug never takes the daemon down.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .swarm import (
    DEFAULT_MAX_IDLE_ROUNDS,
    DEFAULT_WORKER_TIMEOUT,
    REASON_ERROR,
    SwarmResult,
    run_continuous_swarm,
)

DEFAULT_IDLE_SLEEP = 600.0  # poll cadence (s) when there is nothing to build
DEFAULT_FAULT_BACKOFF = 30.0  # first wait (s) after a genuine fault
DEFAULT_FAULT_MAX_BACKOFF = 1800.0  # cap (s) so recovery latency stays bounded


@dataclass(frozen=True)
class DaemonCycle:
    """One supervised swarm run and the daemon's reaction to it."""

    index: int  # 1-based cycle number
    outcome: str  # "progress" | "idle" | "fault"
    reason: str  # underlying SwarmResult.reason (or REASON_ERROR on a crash)
    merged: int  # workers merged this cycle
    error: str | None
    delay: float  # seconds the daemon will sleep before the next cycle


@dataclass(frozen=True)
class DaemonReport:
    """Tallies returned when a daemon run ends (bounded or stopped)."""

    cycles: int
    progress: int
    idle: int
    faults: int
    last_reason: str | None


def _outcome(result: SwarmResult) -> tuple[str, int]:
    """Classify a swarm result into the daemon's three buckets.

    A *genuine* fault — a top-level swarm error such as a failed push or a broken
    verify — carries an error message and must back off so a broken state self-heals,
    even if some work merged. But a round that merged work and only had a worker fail
    its grounded task sets ``reason=REASON_ERROR`` with NO top-level error (the normal
    case: agents do not land every task). That is the backlog draining, not a fault,
    so the daemon loops on immediately per its contract instead of backing off
    mid-progress. Only when nothing merged does a bare ``REASON_ERROR`` back off.
    """
    merged = sum(1 for worker in result.workers if worker.status == "merged")
    if result.reason == REASON_ERROR:
        # A bare REASON_ERROR (no top-level error) with merges is the backlog draining —
        # agents merged some but not all this cycle — so loop on immediately. A genuine
        # fault, or an error cycle that merged nothing, backs off.
        genuine_fault = result.error is not None
        if not genuine_fault and merged:
            return "progress", merged
        return "fault", merged
    # NO_WORK (backlog drained), IDLE (swarm stalled), LIMIT (usage limit) are poll/back-off
    # signals: an early merge before the cycle reached that terminal state does not mean
    # there is more to do right now, so they must not be misread as progress (delay 0).
    return "idle", merged


def run_daemon(
    root: Path,
    *,
    agent: str,
    config: Config,
    workers: int,
    worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    push: bool = False,
    resume_on_limit: bool = True,
    limit_backoff_seconds: float = 30.0,
    limit_max_wait_seconds: float = 3600.0,
    limit_max_resumes: int = 0,
    max_idle_rounds: int = DEFAULT_MAX_IDLE_ROUNDS,
    idle_sleep_seconds: float = DEFAULT_IDLE_SLEEP,
    fault_backoff_seconds: float = DEFAULT_FAULT_BACKOFF,
    fault_max_backoff_seconds: float = DEFAULT_FAULT_MAX_BACKOFF,
    max_cycles: int = 0,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] | None = None,
    run_cycle: Callable[..., SwarmResult] = run_continuous_swarm,
    on_cycle: Callable[[DaemonCycle], None] | None = None,
    on_fault: Callable[[dict], None] | None = None,
) -> DaemonReport:
    """Supervise a continuous swarm so the loop never permanently stops.

    Each cycle runs an unbounded continuous swarm (``max_rounds=0``); it returns
    when the backlog dries up, a usage limit persists, or a fault occurs. The
    daemon then loops again after a delay chosen from the outcome. The injected
    ``sleep`` is responsible for interruptibility — the CLI passes one that aborts
    promptly on SIGTERM/SIGINT so shutdown stays graceful.
    """
    cycles = progress = idle = faults = 0
    fault_streak = 0
    last_reason: str | None = None

    while max_cycles == 0 or cycles < max_cycles:
        if should_stop is not None and should_stop():
            break

        try:
            result = run_cycle(
                root,
                agent=agent,
                config=config,
                workers=workers,
                worker_timeout=worker_timeout,
                push=push,
                max_rounds=0,
                resume_on_limit=resume_on_limit,
                limit_backoff_seconds=limit_backoff_seconds,
                limit_max_wait_seconds=limit_max_wait_seconds,
                limit_max_resumes=limit_max_resumes,
                generate_ideas=config.idea_generation,
                max_idle_rounds=max_idle_rounds,
            )
            outcome, merged = _outcome(result)
            reason, error = result.reason, result.error
        except Exception as exc:  # a bug in a cycle must not kill the daemon
            outcome, merged = "fault", 0
            reason = REASON_ERROR
            error = f"{type(exc).__name__}: {exc}"

        cycles += 1
        last_reason = reason

        if outcome == "fault":
            faults += 1
            fault_streak += 1
            delay = min(
                fault_backoff_seconds * (2 ** (fault_streak - 1)),
                fault_max_backoff_seconds,
            )
        else:
            fault_streak = 0
            if outcome == "progress":
                progress += 1
                delay = 0.0
            else:
                idle += 1
                delay = idle_sleep_seconds

        if on_cycle is not None:
            on_cycle(DaemonCycle(cycles, outcome, reason, merged, error, delay))

        if on_fault is not None and outcome == "fault":
            try:
                on_fault(
                    {"cycle": cycles, "reason": reason, "backoff_s": delay, "last_error": error}
                )
            except Exception:
                pass  # a failing fault hook must never stop the daemon

        if max_cycles and cycles >= max_cycles:
            break
        if should_stop is not None and should_stop():
            break
        if delay:
            sleep(delay)

    return DaemonReport(cycles, progress, idle, faults, last_reason)
