"""Run summary rendering."""

from __future__ import annotations

from io import StringIO

from looptight import summary
from looptight.console import Console
from looptight.types import IterationRecord, RunResult, StopReason, VerifyResult


def _result(stop: StopReason) -> RunResult:
    return RunResult(
        goal="fix tests",
        agent="claude",
        mode="supply",
        stop_reason=stop,
        iterations=(
            IterationRecord(1, VerifyResult(passed=False, exit_code=1)),
            IterationRecord(2, VerifyResult(passed=True, exit_code=0)),
        ),
    )


def test_summary_has_readable_iterations_and_result():
    text = summary.render(_result(StopReason.SUCCESS))
    assert "iteration 1 → verify: FAIL" in text
    assert "iteration 2 → verify: PASS" in text
    assert "✓ done · 2 iteration(s)" in text


def test_summary_shows_stop_reasons():
    assert "iteration cap" in summary.render(_result(StopReason.ITERATION_CAP))
    assert "no measurable progress" in summary.render(_result(StopReason.NO_PROGRESS))
    assert "human" in summary.render(_result(StopReason.ESCALATED))


def test_summary_surfaces_error_message():
    result = RunResult(
        goal="fix",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.ERROR,
        error="git checkout failed: detached HEAD",
    )
    text = summary.render(result)
    assert "git checkout failed: detached HEAD" in text
    # Non-error summaries stay unchanged.
    assert "error" not in summary.render(_result(StopReason.SUCCESS))


def test_summary_includes_diffstat():
    result = RunResult(
        goal="fix",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        diffstat=" src/a.py | 3 +++",
    )
    assert "src/a.py" in summary.render(result)


def test_console_summary_matches_plain_result():
    output = StringIO()
    summary.render_rich(_result(StopReason.SUCCESS), Console(file=output))
    assert "iteration 1 → verify: FAIL" in output.getvalue()
    assert "✓ done · 2 iteration(s)" in output.getvalue()


def test_summary_shows_escalation_evidence_when_present():
    from looptight.types import Escalation

    esc = Escalation(
        kind="escalated",
        iterations=3,
        trajectory=(-2.0, -2.0, -2.0),
        failures=("FAILED tests/test_auth.py::test_login - AssertionError: expected 200",),
        summary="No progress across 3 tries. 1 failure never cleared.",
        persisted=True,
    )
    result = RunResult(
        goal="fix", agent="claude", mode="supply",
        stop_reason=StopReason.ESCALATED,
        iterations=(IterationRecord(1, VerifyResult(passed=False, exit_code=1)),),
        escalation=esc,
    )
    text = summary.render(result)
    assert "No progress across 3 tries. 1 failure never cleared." in text
    assert "tests/test_auth.py::test_login" in text
    # Absent escalation leaves the summary unchanged (no stray evidence block).
    assert "never cleared" not in summary.render(_result(StopReason.SUCCESS))


def _escalated(failures, total):
    from looptight.types import Escalation
    esc = Escalation(
        kind="escalated", iterations=3, trajectory=(-2.0, -2.0, -2.0),
        failures=tuple(failures), summary="No progress across 3 tries. "
        f"{total} failures never cleared.", persisted=True, total_failures=total,
    )
    return RunResult(
        goal="x", agent="claude", mode="supply", stop_reason=StopReason.ESCALATED,
        iterations=(IterationRecord(1, VerifyResult(passed=False, exit_code=1)),),
        escalation=esc,
    )


def test_summary_tail_is_concise_when_escalation_present():
    # The escalation block carries the "why"; the tail must not repeat it.
    text = summary.render(_escalated(["FAILED a::x - boom"], 1))
    assert "stopped early" in text
    assert "worth a human look" not in text  # no duplicate verdict
    assert "No progress across 3 tries" in text  # the why is still there


def test_summary_indicates_truncated_failure_list():
    shown = [f"FAILED a::t{i} - boom" for i in range(10)]
    text = summary.render(_escalated(shown, total=13))
    assert "… and 3 more" in text  # 13 total, 10 shown
    # At or under the cap, no overflow line.
    assert "more" not in summary.render(_escalated(["FAILED a::x - boom"], 1))


def test_summary_header_delegate_mode():
    result = RunResult(
        goal="fix tests",
        agent="claude",
        mode="delegate",
        stop_reason=StopReason.SUCCESS,
    )
    assert "driving native loop" in summary.header(result)


def test_console_summary_includes_diffstat():
    output = StringIO()
    result = RunResult(
        goal="fix",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.SUCCESS,
        diffstat=" src/a.py | 3 +++",
    )
    summary.render_rich(result, Console(file=output))
    text = output.getvalue()
    assert "changes:" in text
    assert "src/a.py" in text
