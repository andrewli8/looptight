"""Run summary rendering (E1, E2)."""

from __future__ import annotations

from looptight import summary
from looptight.types import IterationRecord, Lesson, RunResult, StopReason, VerifyResult


def _result(stop: StopReason, *, lesson: Lesson | None = None) -> RunResult:
    records = (
        IterationRecord(1, VerifyResult(passed=False, exit_code=1), 0.04),
        IterationRecord(2, VerifyResult(passed=True, exit_code=0), 0.09),
    )
    return RunResult(
        goal="fix tests",
        agent="claude",
        mode="supply",
        stop_reason=stop,
        iterations=records,
        total_cost_usd=0.13,
        lesson=lesson,
    )


def test_summary_has_gifable_iteration_lines():
    text = summary.render(_result(StopReason.SUCCESS))
    assert "iteration 1 → verify: FAIL" in text
    assert "iteration 2 → verify: PASS" in text


def test_summary_shows_success_marker_and_cost():
    text = summary.render(_result(StopReason.SUCCESS))
    assert "✓" in text
    assert "$0.13" in text


def test_summary_shows_stop_reason_when_capped():
    text = summary.render(_result(StopReason.ITERATION_CAP))
    assert "iteration cap" in text
    assert "✗" in text


def test_summary_includes_saved_lesson():
    text = summary.render(_result(StopReason.SUCCESS, lesson=Lesson(text="Pin the timeout")))
    assert "lesson saved: Pin the timeout" in text


def test_header_names_mode():
    text = summary.render(_result(StopReason.SUCCESS))
    assert "supplying loop" in text


def test_summary_explains_value_aware_stops():
    assert "no measurable progress" in summary.render(_result(StopReason.NO_PROGRESS))
    assert "human" in summary.render(_result(StopReason.ESCALATED))
