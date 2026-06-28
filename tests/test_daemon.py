"""Tests for the daemon supervisor that keeps the continuous swarm running."""

from __future__ import annotations

from pathlib import Path

from looptight.config import Config
from looptight.daemon import DEFAULT_FAULT_BACKOFF, DaemonCycle, _outcome, run_daemon
from looptight.swarm import (
    REASON_ERROR,
    REASON_IDLE,
    REASON_LIMIT,
    REASON_NO_WORK,
    REASON_OK,
    SwarmResult,
    Worker,
)


def _result(reason: str = REASON_OK, merged: int = 0, error: str | None = None) -> SwarmResult:
    workers = tuple(
        Worker(
            number=i + 1,
            task=None,
            branch="b",
            worktree=Path("/tmp/wt"),
            base="base",
            status="merged",
        )
        for i in range(merged)
    )
    return SwarmResult(workers, error=error, reason=reason)


class _Recorder:
    """Drives run_daemon with a scripted sequence of cycle outcomes."""

    def __init__(self, results: list[SwarmResult]):
        self._results = results
        self.calls: list[dict] = []
        self.sleeps: list[float] = []
        self.cycles: list[DaemonCycle] = []

    def run_cycle(self, root, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return self._results[min(index, len(self._results) - 1)]

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def on_cycle(self, cycle):
        self.cycles.append(cycle)


def _config() -> Config:
    return Config(verify="pytest -q", agent="claude")


def test_daemon_stops_after_max_cycles_and_sleeps_between_only():
    rec = _Recorder([_result(REASON_IDLE)])
    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=3,
        idle_sleep_seconds=600.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    assert report.cycles == 3
    assert report.idle == 3
    # A daemon sleeps *between* cycles, never after the final one it will run.
    assert rec.sleeps == [600.0, 600.0]


def test_outcome_treats_idle_and_no_work_as_idle_despite_early_merges():
    # A cumulative merge earlier in a cycle must not flip a back-off signal to progress:
    # REASON_IDLE (swarm stalled) and REASON_NO_WORK (backlog drained) poll/back off even
    # when a worker merged before the cycle reached that terminal state — otherwise the
    # daemon re-attacks a degenerate planner state with no delay, burning model calls.
    assert _outcome(_result(REASON_IDLE, merged=1)) == ("idle", 1)
    assert _outcome(_result(REASON_NO_WORK, merged=2)) == ("idle", 2)
    assert _outcome(_result(REASON_LIMIT, merged=1)) == ("idle", 1)
    # Only a draining REASON_ERROR (some merged, no top-level error) loops on with delay 0.
    assert _outcome(_result(REASON_ERROR, merged=1, error=None)) == ("progress", 1)
    assert _outcome(_result(REASON_ERROR, merged=0, error="boom"))[0] == "fault"
    assert _outcome(_result(REASON_ERROR, merged=0))[0] == "fault"  # bare error, nothing merged


def test_daemon_runs_progress_cycles_back_to_back_without_sleeping():
    # A draining backlog (REASON_ERROR, some merged, no top-level error) loops on with no delay.
    rec = _Recorder([_result(REASON_ERROR, merged=1, error=None)])
    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=2,
        idle_sleep_seconds=600.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    assert report.progress == 2
    assert rec.sleeps == []  # merged progress => drain promptly, no back-off
    assert rec.cycles[0].outcome == "progress"


def test_daemon_backs_off_exponentially_on_faults_then_caps():
    rec = _Recorder([_result(REASON_ERROR, error="boom")])
    run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=5,
        fault_backoff_seconds=30.0,
        fault_max_backoff_seconds=120.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    # 30, 60, 120, capped at 120 — one fewer sleep than cycles (none after the last).
    assert rec.sleeps == [30.0, 60.0, 120.0, 120.0]


def test_daemon_fault_streak_resets_after_progress():
    rec = _Recorder(
        [
            _result(REASON_ERROR, error="boom"),
            _result(REASON_ERROR, error="boom"),
            _result(REASON_ERROR, merged=1, error=None),  # draining: progress, resets streak
            _result(REASON_ERROR, error="boom"),
            _result(REASON_IDLE),
        ]
    )
    run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=5,
        fault_backoff_seconds=30.0,
        fault_max_backoff_seconds=10_000.0,
        idle_sleep_seconds=600.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    # fault(30), fault(60), progress(no sleep), fault(back to 30 — streak reset),
    # then the final idle cycle runs but never sleeps.
    assert rec.sleeps == [30.0, 60.0, 30.0]


def test_daemon_treats_a_merged_round_as_progress_despite_reason_error():
    # A round that merged work but had a worker fail its grounded task returns
    # reason=REASON_ERROR with NO top-level error (the normal case — agents do not
    # land every task). That is the backlog draining, not a fault: the daemon must
    # loop on immediately (delay 0) per its contract, not back off mid-progress.
    rec = _Recorder([_result(REASON_ERROR, merged=1, error=None)])
    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=1,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    assert report.progress == 1
    assert report.faults == 0
    assert rec.cycles[0].outcome == "progress"
    assert rec.cycles[0].delay == 0.0


def test_daemon_backs_off_on_a_genuine_error_even_with_merged_work():
    # A genuine top-level fault (a real error message — failed push, broken verify)
    # still backs off even if some work merged: a broken state must self-heal and
    # not hot-loop. The distinction from the case above is the present error string.
    rec = _Recorder([_result(REASON_ERROR, merged=1, error="push rejected")])
    run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=1,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    assert rec.cycles[0].outcome == "fault"


def test_daemon_treats_limit_as_idle_not_fault():
    rec = _Recorder([_result(REASON_LIMIT, error="usage limit persisted")])
    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=2,
        idle_sleep_seconds=300.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        on_cycle=rec.on_cycle,
    )
    assert report.faults == 0
    assert report.idle == 2
    assert rec.sleeps == [300.0]


def test_daemon_halts_when_should_stop_returns_true():
    rec = _Recorder([_result(REASON_IDLE)])

    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        idle_sleep_seconds=1.0,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
        should_stop=lambda: len(rec.calls) >= 2,  # stop once two cycles have run
        on_cycle=rec.on_cycle,
    )
    assert report.cycles == 2


def test_daemon_survives_an_exception_from_a_cycle():
    boom = {"raised": False}

    def run_cycle(root, **kwargs):
        if not boom["raised"]:
            boom["raised"] = True
            raise RuntimeError("worker crashed hard")
        return _result(REASON_NO_WORK)

    sleeps: list[float] = []
    cycles: list[DaemonCycle] = []
    report = run_daemon(
        Path("."),
        agent="claude",
        config=_config(),
        workers=2,
        max_cycles=2,
        fault_backoff_seconds=5.0,
        sleep=sleeps.append,
        run_cycle=run_cycle,
        on_cycle=cycles.append,
    )
    # The crash is absorbed as a fault; the daemon keeps going instead of dying.
    assert report.cycles == 2
    assert report.faults == 1
    assert cycles[0].outcome == "fault"
    assert "worker crashed hard" in (cycles[0].error or "")
    assert sleeps == [5.0]


def test_daemon_drives_an_unbounded_continuous_swarm_with_idea_generation():
    rec = _Recorder([_result(REASON_NO_WORK)])
    cfg = Config(verify="pytest -q", agent="claude", idea_generation=True)
    run_daemon(
        Path("."),
        agent="claude",
        config=cfg,
        workers=3,
        push=True,
        resume_on_limit=True,
        max_cycles=1,
        sleep=rec.sleep,
        run_cycle=rec.run_cycle,
    )
    call = rec.calls[0]
    assert call["max_rounds"] == 0  # each cycle drains until the backlog is dry
    assert call["resume_on_limit"] is True
    assert call["generate_ideas"] is True
    assert call["push"] is True
    assert call["workers"] == 3


def test_default_fault_backoff_is_sane():
    assert 0 < DEFAULT_FAULT_BACKOFF <= 60.0


# --- optional fault hook (--on-fault) ---

def test_daemon_fires_on_fault_with_payload():
    rec = _Recorder([_result(REASON_ERROR, error="boom")])
    faults = []
    run_daemon(
        Path("."), agent="claude", config=_config(), workers=2,
        max_cycles=1, fault_backoff_seconds=30.0,
        sleep=rec.sleep, run_cycle=rec.run_cycle, on_fault=faults.append,
    )
    assert faults == [
        {"cycle": 1, "reason": REASON_ERROR, "backoff_s": 30.0, "last_error": "boom"}
    ]


def test_daemon_on_fault_not_called_on_idle_or_progress():
    rec = _Recorder([_result(REASON_IDLE)])
    faults = []
    run_daemon(
        Path("."), agent="claude", config=_config(), workers=2, max_cycles=1,
        sleep=rec.sleep, run_cycle=rec.run_cycle, on_fault=faults.append,
    )
    assert faults == []


def test_daemon_survives_a_failing_on_fault_hook():
    rec = _Recorder([_result(REASON_ERROR, error="boom")])

    def boom(_payload):
        raise RuntimeError("hook blew up")

    report = run_daemon(
        Path("."), agent="claude", config=_config(), workers=2,
        max_cycles=2, fault_backoff_seconds=5.0,
        sleep=rec.sleep, run_cycle=rec.run_cycle, on_fault=boom,
    )
    assert report.cycles == 2
    assert report.faults == 2  # the daemon kept going despite the hook raising


def test_outcome_genuine_fault_with_merged_workers():
    # _outcome() returns ("fault", merged>0) for a GENUINE fault — a top-level error
    # message is present (a failed push, a broken verify) — even if some workers
    # merged before it: a broken state must back off. A merged round with NO
    # top-level error is progress, not a fault (covered separately).
    result = _result(REASON_ERROR, merged=1, error="push rejected")
    outcome, merged = _outcome(result)
    assert outcome == "fault"
    assert merged == 1
