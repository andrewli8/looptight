"""Value-aware stopping controller (Phase 1): signal parsing + policy."""

from __future__ import annotations

from looptight.checkpoint import Checkpointer
from looptight.config import Config
from looptight.loop import run_loop
from looptight.metacog import Decision, assess, progress_signal
from looptight.types import IterationRecord, StopReason, VerifyResult

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


def test_progress_signal_returns_none_for_passing_verify():
    # metacog.py:49 — the `if verify.passed: return None` early exit has no direct
    # unit test; a regression replacing it with a fallthrough would compute -0.0
    # instead of None, silently changing the controller's "no signal, keep going" logic.
    assert progress_signal(VerifyResult(passed=True, exit_code=0, output="0 failed")) is None


# --- assess ----------------------------------------------------------------

def test_patience_zero_always_continues():
    assert assess([-3.0, -3.0, -3.0], patience=0) is Decision.CONTINUE


def test_continues_without_enough_history():
    assert assess([-3.0, -2.0], patience=2) is Decision.CONTINUE


def test_continues_while_improving():
    assert assess([-5.0, -4.0, -3.0], patience=2) is Decision.CONTINUE


def test_stops_after_progress_then_plateau():
    assert assess([-5.0, -3.0, -3.0, -3.0], patience=2) is Decision.STOP_NO_PROGRESS


def test_stops_after_progress_then_regression():
    # improved from -5 to -3 then lost ground to -4: still STOP_NO_PROGRESS
    assert assess([-5.0, -3.0, -4.0, -4.0], patience=2) is Decision.STOP_NO_PROGRESS


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
    base = dict(verify="pytest -q", agent="fake", max_iterations=10)
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


# --- escalation evidence ---------------------------------------------------

def _rec(number: int, output: str) -> IterationRecord:
    return IterationRecord(number=number, verify=VerifyResult(passed=False, exit_code=1, output=output))


def test_failure_lines_extracts_and_normalizes_across_runners():
    from looptight.metacog import _failure_lines

    pytest_out = "FAILED tests/test_auth.py::test_login - AssertionError: expected 200\n5 passed"
    jest_out = "  ✕ renders the header (12 ms)\n  ✓ ok"
    go_out = "--- FAIL: TestRefund (0.01s)\nok other"

    assert any("test_login" in line for line in _failure_lines(pytest_out))
    assert any("renders the header" in line for line in _failure_lines(jest_out))
    assert any("TestRefund" in line for line in _failure_lines(go_out))
    # A passing/noise line is not a failure line.
    assert _failure_lines("5 passed in 0.1s\nok") == set()
    # A count tally is not failure evidence (it inflates the count and adds noise).
    summary_out = "=== 2 failed, 18 passed in 0.4s ===\nFAILED a::x - boom"
    failures = _failure_lines(summary_out)
    assert any("a::x" in line for line in failures)
    assert not any("18 passed" in line for line in failures)
    assert len(failures) == 1  # only the real failure, not the tally


def test_failure_lines_returns_empty_set_for_none_and_empty_output():
    from looptight.metacog import _failure_lines

    assert _failure_lines(None) == set()
    assert _failure_lines("") == set()


def test_failure_lines_detects_tap_not_ok():
    from looptight.metacog import _failure_lines

    # TAP-format failure (Node.js tap, node:test) — mutating "not ok" out of
    # _FAILURE_LINE_RE would make this return empty and fail this assertion.
    result = _failure_lines("not ok 1 - login fails")
    assert result, "not ok TAP line must be detected as a failure"
    assert any("login fails" in line for line in result)


def test_failure_lines_detects_python_traceback():
    from looptight.metacog import _failure_lines

    # Python exception output — mutating "Traceback" out of _FAILURE_LINE_RE
    # would make this return empty and fail this assertion.
    output = "Traceback (most recent call last):\n  File test.py, line 5"
    result = _failure_lines(output)
    assert result, "Traceback line must be detected as a failure"
    assert any("Traceback" in line for line in result)


def test_normalize_merges_failures_differing_only_by_duration():
    from looptight.metacog import _failure_lines

    a = _failure_lines("--- FAIL: TestRefund (0.01s)")
    b = _failure_lines("--- FAIL: TestRefund (1.42s)")
    assert a == b  # the volatile duration is normalized away


def test_normalize_failure_replaces_hex_addresses():
    from looptight.metacog import _normalize_failure
    result = _normalize_failure("FAILED: segfault at 0xDEADBEEF in heap")
    assert "0xADDR" in result
    assert "0xDEADBEEF" not in result


def test_normalize_failure_normalizes_in_seconds_fragment():
    from looptight.metacog import _normalize_failure
    result = _normalize_failure("FAILED: connection timed out in 2ms")
    assert "in 2ms" not in result
    assert "in Ns" in result


def test_normalize_failure_normalizes_plain_seconds_fragment():
    # metacog.py:106 — `m?s` matches both `ms` and `s`; the only prior test uses `in 2ms`,
    # so a mutation dropping `m?` (making `ms` mandatory) leaves `in 2s` un-normalized.
    from looptight.metacog import _normalize_failure

    result = _normalize_failure("FAILED: connection timed out in 2s")
    assert "in 2s" not in result
    assert "in Ns" in result


def test_normalize_failure_truncates_at_max_failure_line():
    # metacog.py:115 — `[:MAX_FAILURE_LINE]` caps the output at 200 chars; both existing
    # tests use short strings so a mutation raising the cap would go undetected.
    from looptight.metacog import MAX_FAILURE_LINE, _normalize_failure

    long_line = "x" * 300
    result = _normalize_failure(long_line)
    assert len(result) == MAX_FAILURE_LINE


def test_persistent_failures_keeps_only_what_never_cleared():
    from looptight.metacog import persistent_failures

    records = [
        _rec(1, "FAILED a::x - boom\nFAILED a::y - bad"),
        _rec(2, "FAILED a::x - boom"),  # y cleared this round
    ]
    failures, persisted = persistent_failures(records)
    assert persisted is True
    assert any("a::x" in f for f in failures)
    assert not any("a::y" in f for f in failures)  # cleared, so not persistent


def test_persistent_failures_falls_back_to_final_when_no_overlap():
    from looptight.metacog import persistent_failures

    records = [_rec(1, "FAILED a::x - boom"), _rec(2, "FAILED b::z - nope")]
    failures, persisted = persistent_failures(records)
    assert persisted is False  # nothing held across both rounds
    assert any("b::z" in f for f in failures)  # the most recent failures


def test_persistent_failures_empty_when_nothing_parses():
    from looptight.metacog import persistent_failures

    assert persistent_failures([_rec(1, "kaboom"), _rec(2, "kaboom")]) == ((), True)


def test_persistent_from_sets_ignores_an_unparseable_middle_iteration():
    # A noise iteration (timeout / unrecognized output) yields an empty set; it must not
    # erase a failure that held across every *meaningful* try. Evidence-only — never the
    # stop/escalate decision.
    from looptight.metacog import persistent_from_sets

    failures, persisted = persistent_from_sets([{"FAILED a::x"}, set(), {"FAILED a::x"}])
    assert persisted is True
    assert failures == ("FAILED a::x",)


def test_build_escalation_distinguishes_kind_and_carries_evidence():
    from looptight.metacog import build_escalation

    records = [_rec(1, "FAILED a::x - boom"), _rec(2, "FAILED a::x - boom")]
    esc = build_escalation(records, [-1.0, -1.0], StopReason.ESCALATED)
    assert esc.kind == "escalated"
    assert esc.iterations == 2
    assert esc.trajectory == (-1.0, -1.0)
    assert any("a::x" in f for f in esc.failures)
    assert "1 failure" in esc.summary  # one failure never cleared

    esc2 = build_escalation(records, [-3.0, -1.0], StopReason.NO_PROGRESS)
    assert esc2.kind == "no_progress"


def test_loop_attaches_escalation_on_early_stops(workdir):
    stuck = _run(workdir, ["2 failed", "2 failed", "2 failed"], patience=2)
    assert stuck.stop_reason is StopReason.ESCALATED
    assert stuck.escalation is not None
    assert stuck.escalation.kind == "escalated"
    assert any("failed" in f.lower() or "fail" in f.lower() for f in stuck.escalation.failures) \
        or stuck.escalation.failures == ()

    improving = _run(workdir, ["5 failed", "3 failed", "3 failed", "3 failed"], patience=2)
    assert improving.stop_reason is StopReason.NO_PROGRESS
    assert improving.escalation is not None
    assert improving.escalation.kind == "no_progress"


def test_loop_leaves_escalation_none_on_success_and_cap(workdir):
    state = {"n": 0}

    def passes_on_second(command, cwd):
        state["n"] += 1
        if state["n"] >= 2:
            return VerifyResult(passed=True, exit_code=0)
        return VerifyResult(passed=False, exit_code=1, output="1 failed")

    ok = run_loop(
        "fix it", FakeAdapter(), _cfg(patience=2), workdir,
        verify_fn=passes_on_second, checkpointer=Checkpointer(workdir, enabled=False),
    )
    assert ok.stop_reason is StopReason.SUCCESS
    assert ok.escalation is None

    capped = _run(workdir, ["2 failed"], patience=0, max_iterations=3)
    assert capped.stop_reason is StopReason.ITERATION_CAP
    assert capped.escalation is None


def test_persistent_from_sets_matches_record_based(workdir=None):
    from looptight.metacog import persistent_from_sets, persistent_failures
    sets = [{"FAILED a::x - boom", "FAILED a::y - bad"}, {"FAILED a::x - boom"}]
    lines, persisted = persistent_from_sets(sets)
    assert persisted is True and any("a::x" in line for line in lines)
    assert not any("a::y" in line for line in lines)
    # The record-based wrapper produces the same result for equivalent output.
    recs = [_rec(1, "FAILED a::x - boom\nFAILED a::y - bad"), _rec(2, "FAILED a::x - boom")]
    assert persistent_failures(recs) == (lines, persisted)


def test_persistent_from_sets_empty_list_returns_empty_tuple():
    from looptight.metacog import persistent_from_sets

    result = persistent_from_sets([])
    assert result == ((), True)


def test_escalation_from_signals_builds_the_same_report():
    from looptight.metacog import escalation_from_signals
    sets = [{"FAILED a::x - boom"}, {"FAILED a::x - boom"}]
    esc = escalation_from_signals([-1.0, -1.0], sets, StopReason.ESCALATED)
    assert esc.kind == "escalated"
    assert esc.iterations == 2
    assert esc.trajectory == (-1.0, -1.0)
    assert any("a::x" in f for f in esc.failures)
    assert "1 failure" in esc.summary


def test_summarize_no_failures_parsed_branch():
    # total == 0: the "No specific failures parsed" branch is distinct from the
    # "never cleared" and "Showing the latest" branches.
    from looptight.metacog import _summarize
    text = _summarize("escalated", total=0, persisted=True, iterations=2)
    assert "No specific failures parsed" in text
    assert "never cleared" not in text


def test_summarize_non_persistent_failures_branch():
    # persisted == False: "Showing the latest ... none held across every try."
    from looptight.metacog import _summarize
    text = _summarize("no_progress", total=3, persisted=False, iterations=2)
    assert "Showing the latest" in text
    assert "none held" in text
    assert "never cleared" not in text


def test_summarize_no_progress_persisted_failures():
    # no_progress + total > 0 + persisted=True: an honest umbrella that covers both a
    # stall and a regress (the branch fires for improve-then-regress too), plus the
    # persisted-failure tail.
    from looptight.metacog import _summarize
    text = _summarize("no_progress", total=2, persisted=True, iterations=3)
    assert "made no further progress" in text
    assert "stalled" not in text  # "stalled" alone would misreport a regress
    assert "never cleared" in text


def test_summarize_single_iteration_uses_singular_try():
    # iterations == 1: "1 try" not "1 tries".
    from looptight.metacog import _summarize
    text = _summarize("escalated", total=1, persisted=True, iterations=1)
    assert "1 try" in text
    assert "tries" not in text
