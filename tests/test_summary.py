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
    assert "✓ done · 2 iterations" in text  # proper plural


def test_summary_renders_singular_iteration():
    # The n != 1 guard at summary.py:74 must produce "1 iteration" without a trailing 's'.
    assert summary._iterations(1) == "1 iteration"


def test_summary_shows_stop_reasons():
    assert "iteration cap" in summary.render(_result(StopReason.ITERATION_CAP))
    assert "no measurable progress" in summary.render(_result(StopReason.NO_PROGRESS))
    assert "human" in summary.render(_result(StopReason.ESCALATED))


def test_summary_shows_no_verify_stop_reason():
    # summary.py:18 — NO_VERIFY entry in _REASON_TEXT must produce the human-readable phrase,
    # not the snake_case fallback from result.stop_reason.value.
    text = summary.render(RunResult(goal="x", agent="claude", mode="supply", stop_reason=StopReason.NO_VERIFY))
    assert "no verify command" in text


def test_summary_shows_agent_unavailable_stop_reason():
    # summary.py:19 — AGENT_UNAVAILABLE entry in _REASON_TEXT must produce the human-readable
    # phrase, not "agent_unavailable", so the user knows to install or configure an agent.
    text = summary.render(RunResult(goal="x", agent="claude", mode="supply", stop_reason=StopReason.AGENT_UNAVAILABLE))
    assert "no coding agent found on PATH" in text


def test_zero_iteration_summary_has_no_double_blank():
    # A run that fails before any iteration (e.g. the agent crashes) must not print two blank
    # lines between the header/banner and the conclusion.
    result = RunResult(
        goal="fix", agent="claude", mode="supply", stop_reason=StopReason.ERROR, error="claude exited 3"
    )
    assert "\n\n\n" not in summary.render(result)  # plain artifact
    out = StringIO()
    summary.render_rich(result, Console(file=out))
    assert "\n\n\n" not in out.getvalue()  # standalone rich
    out2 = StringIO()
    summary.render_rich(result, Console(file=out2), include_progress=False)
    assert "\n\n\n" not in out2.getvalue()  # cmd_run conclusion-only
    # A multi-iteration summary still separates the iterations from the conclusion.
    assert "✓ done · 2 iterations" in summary.render(_result(StopReason.SUCCESS))


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


def test_summary_tail_error_without_message_omits_detail():
    # When stop_reason=ERROR but error=None the _tail fallback (summary.py:37) returns the bare
    # reason text without an appended ": <detail>" suffix from result.error.
    result = RunResult(goal="fix", agent="claude", mode="supply", stop_reason=StopReason.ERROR, error=None)
    tail = summary._tail(result)
    assert "error" in tail
    # The tail must equal the bare reason text — no extra detail appended.
    assert tail == "stopped: error"


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
    assert "✓ done · 2 iterations" in output.getvalue()  # proper plural


def test_render_rich_can_omit_progress_for_cmd_run():
    # cmd_run streams the banner + iterations live, so the summary must print only the conclusion
    # (no duplicate header/iteration list).
    output = StringIO()
    summary.render_rich(_result(StopReason.SUCCESS), Console(file=output), include_progress=False)
    out = output.getvalue()
    assert "iteration 1 → verify:" not in out  # not reprinted
    assert "supplying loop" not in out  # header not reprinted
    assert "done" in out  # the conclusion is still shown


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


def test_render_rich_shows_escalation_evidence_in_rich_output():
    from looptight.types import Escalation

    esc = Escalation(
        kind="escalated",
        iterations=2,
        trajectory=(-3.0, -3.0),
        failures=("FAILED tests/test_auth.py::test_login",),
        summary="No progress across 2 tries. 1 failure never cleared.",
        persisted=True,
    )
    output = StringIO()
    result = RunResult(
        goal="fix auth",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.ESCALATED,
        iterations=(IterationRecord(1, VerifyResult(passed=False, exit_code=1)),),
        escalation=esc,
    )
    summary.render_rich(result, Console(file=output))
    text = output.getvalue()
    assert "No progress across 2 tries. 1 failure never cleared." in text
    assert "tests/test_auth.py::test_login" in text


def test_run_result_as_dict_serializes_escalation_keys():
    # types.py:168 — the non-None escalation branch of RunResult.as_dict() must include
    # all expected keys; a regression removing a key would silently break `run --json`.
    from looptight.types import Escalation

    esc = Escalation(
        kind="escalated",
        iterations=2,
        trajectory=(-2.0, -2.0),
        failures=("FAILED tests/test_auth.py::test_login - AssertionError",),
        summary="No progress across 2 tries. 1 failure never cleared.",
        persisted=True,
        total_failures=1,
    )
    result = RunResult(
        goal="fix auth",
        agent="claude",
        mode="supply",
        stop_reason=StopReason.ESCALATED,
        escalation=esc,
    )
    d = result.as_dict()
    esc_dict = d["escalation"]
    assert isinstance(esc_dict, dict)
    for key in ("kind", "failures", "trajectory", "summary", "persisted", "total_failures"):
        assert key in esc_dict, f"as_dict()['escalation'] missing key {key!r}"
    assert esc_dict["kind"] == "escalated"
    assert esc_dict["persisted"] is True
    assert esc_dict["total_failures"] == 1


def test_iteration_record_line_format():
    # types.py:93 — direct unit test for IterationRecord.line() so the exact
    # "iteration N → verify: …" format is pinned independently of render().
    rec_pass = IterationRecord(3, VerifyResult(passed=True, exit_code=0))
    rec_fail = IterationRecord(7, VerifyResult(passed=False, exit_code=1))
    assert "iteration 3" in rec_pass.line()
    assert "PASS" in rec_pass.line()
    assert "iteration 7" in rec_fail.line()
    assert "FAIL" in rec_fail.line()
