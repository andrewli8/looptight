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


def test_summary_omits_dollar_cost_when_agent_does_not_report_it():
    # codex/opencode report no USD cost; showing "$0.00" reads as "free" when the
    # run was actually provider-billed. Be honest instead of misleading.
    result = RunResult(
        goal="fix tests",
        agent="codex",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        iterations=(IterationRecord(1, VerifyResult(passed=True, exit_code=0), 0.0),),
        total_cost_usd=0.0,
        reports_cost_usd=False,
    )
    text = summary.render(result)
    assert "$0.00" not in text
    assert "cost not reported" in text


def test_summary_includes_diffstat():
    result = RunResult(
        goal="fix",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        diffstat=" src/a.py | 3 +++",
    )
    text = summary.render(result)
    assert "changes:" in text
    assert "src/a.py" in text


def test_render_rich_covers_the_user_facing_summary():
    # render_rich is what `looptight run` actually prints; cover it (incl. the
    # cost-honesty branch) so a bug in the user-facing path can't ship unseen.
    from rich.console import Console

    reported = RunResult(
        goal="fix",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        iterations=(IterationRecord(1, VerifyResult(passed=True, exit_code=0), 0.07),),
        total_cost_usd=0.07,
        lesson=Lesson(text="Pin the timeout"),
        diffstat=" src/a.py | 2 +-",
    )
    console = Console(force_terminal=False)
    with console.capture() as cap:
        summary.render_rich(reported, console)
    out = cap.get()
    assert "iteration 1 → verify: PASS" in out
    assert "$0.07" in out
    assert "lesson saved: Pin the timeout" in out
    assert "src/a.py" in out

    unreported = RunResult(
        goal="fix",
        agent="codex",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        iterations=(IterationRecord(1, VerifyResult(passed=True, exit_code=0), 0.0),),
        total_cost_usd=0.0,
        reports_cost_usd=False,
    )
    with console.capture() as cap:
        summary.render_rich(unreported, console)
    out = cap.get()
    assert "cost not reported" in out
    assert "$0.00" not in out
