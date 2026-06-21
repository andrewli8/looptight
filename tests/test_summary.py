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
