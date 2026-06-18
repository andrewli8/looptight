"""Value-aware stopping controller (Phase 1): signal parsing + policy."""

from __future__ import annotations

from looptight.checkpoint import Checkpointer
from looptight.config import Config
from looptight.loop import run_loop
from looptight.metacog import Decision, assess, progress_signal
from looptight.types import StopReason, VerifyResult

from conftest import FakeAdapter


# --- progress_signal -------------------------------------------------------

def test_progress_counts_failures_negated():
    v = VerifyResult(passed=False, exit_code=1, output="=== 3 failed, 5 passed in 0.1s ===")
    assert progress_signal(v) == -3.0


def test_progress_parses_failing_phrasing():
    v = VerifyResult(passed=False, exit_code=1, output="1 failing test in test_foo.py: AssertionError")
    assert progress_signal(v) == -1.0


def test_progress_sums_failed_and_errors():
    v = VerifyResult(passed=False, exit_code=1, output="2 failed, 1 error")
    assert progress_signal(v) == -3.0


def test_progress_prefers_explicit_score():
    v = VerifyResult(passed=False, exit_code=1, output="2 failed", score=0.8)
    assert progress_signal(v) == 0.8


def test_progress_none_when_unparseable():
    assert progress_signal(VerifyResult(passed=False, exit_code=1, output="kaboom")) is None


# --- assess ----------------------------------------------------------------

def test_patience_zero_always_continues():
    assert assess([-3.0, -3.0, -3.0], patience=0) is Decision.CONTINUE


def test_continues_without_enough_history():
    assert assess([-3.0, -2.0], patience=2) is Decision.CONTINUE


def test_continues_while_improving():
    assert assess([-5.0, -4.0, -3.0], patience=2) is Decision.CONTINUE


def test_stops_after_progress_then_plateau():
    assert assess([-5.0, -3.0, -3.0, -3.0], patience=2) is Decision.STOP_NO_PROGRESS


def test_escalates_when_never_improved():
    assert assess([-3.0, -3.0, -3.0], patience=2) is Decision.ESCALATE


def test_unknown_signals_do_not_trigger_a_stop():
    assert assess([None, None, -3.0], patience=2) is Decision.CONTINUE


# --- integration through the loop -----------------------------------------

def _verify_sequence(outputs):
    """A verify_fn that walks a fixed list of failing outputs (never passes)."""
    state = {"n": 0}

    def fn(command, cwd):
        out = outputs[min(state["n"], len(outputs) - 1)]
        state["n"] += 1
        return VerifyResult(passed=False, exit_code=1, output=out)

    return fn


def _cfg(**kw):
    base = dict(verify="pytest -q", agent="fake", max_iterations=10, budget_usd=10.0)
    base.update(kw)
    return Config(**base)


def _run(workdir, outputs, **cfg):
    return run_loop(
        "fix it",
        FakeAdapter(),
        _cfg(**cfg),
        workdir,
        verify_fn=_verify_sequence(outputs),
        checkpointer=Checkpointer(workdir, enabled=False),
    )


def test_loop_stops_early_on_plateau(workdir):
    result = _run(workdir, ["3 failed", "2 failed", "2 failed", "2 failed", "2 failed"], patience=2)
    assert result.stop_reason is StopReason.NO_PROGRESS
    assert result.iteration_count == 4  # well short of the cap of 10


def test_loop_escalates_when_stuck_from_the_start(workdir):
    result = _run(workdir, ["2 failed", "2 failed", "2 failed"], patience=2)
    assert result.stop_reason is StopReason.ESCALATED
    assert result.iteration_count == 3


def test_disabled_controller_runs_to_cap(workdir):
    result = _run(workdir, ["2 failed"], patience=0, max_iterations=4)
    assert result.stop_reason is StopReason.ITERATION_CAP
    assert result.iteration_count == 4


def test_unparseable_output_falls_back_to_cap(workdir):
    result = _run(workdir, ["kaboom"], patience=2, max_iterations=4)
    assert result.stop_reason is StopReason.ITERATION_CAP
    assert result.iteration_count == 4
