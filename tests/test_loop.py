"""End-to-end loop behaviour with injected fakes."""

from __future__ import annotations

from looptight.checkpoint import Checkpointer
from looptight.config import Config
from looptight.loop import _CONTEXT_OUTPUT_LIMIT, _continuation_context, run_loop
from looptight.types import IterationResult, StopReason, VerifyResult

from conftest import FakeAdapter, make_verify


def _config(**kw) -> Config:
    base = dict(verify="pytest -q", agent="fake", max_iterations=5)
    base.update(kw)
    return Config(**base)


def _run(adapter, config, workdir, *, pass_on):
    return run_loop(
        "fix the failing tests",
        adapter,
        config,
        workdir,
        verify_fn=make_verify(pass_on),
        checkpointer=Checkpointer(workdir, enabled=False),
    )


def test_stops_on_first_pass(workdir):
    adapter = FakeAdapter()
    result = _run(adapter, _config(), workdir, pass_on=2)
    assert result.stop_reason is StopReason.SUCCESS
    assert result.passed
    assert result.iteration_count == 2
    assert adapter.iterations_run == 2


class _LimitedThenOkAdapter(FakeAdapter):
    """Reports a usage limit for its first ``limited`` calls, then works."""

    def __init__(self, *, limited: int, retry: str = "; retry after 5s") -> None:
        super().__init__()
        self._limited = limited
        self._retry = retry

    def run_iteration(self, goal, context, workdir, model=None):
        self.iterations_run += 1
        self.contexts.append(context)
        if self.iterations_run <= self._limited:
            return IterationResult(
                transcript="rate limited", ok=False, error="provider rate limit reached" + self._retry
            )
        return IterationResult(transcript=f"attempt {self.iterations_run}", ok=True)


def test_supply_loop_waits_out_usage_limit_then_succeeds(workdir):
    # Two limit responses, then a real iteration that verify passes.
    adapter = _LimitedThenOkAdapter(limited=2)
    waits: list[float] = []
    result = run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
        resume_on_limit=True,
        sleep=waits.append,
    )

    assert result.stop_reason is StopReason.SUCCESS
    assert result.iteration_count == 1  # the limit retries cost no iteration-cap slot
    assert waits == [5.0, 5.0]  # honored the provider's named reset each time


def test_supply_loop_limit_is_terminal_without_resume(workdir):
    adapter = _LimitedThenOkAdapter(limited=1)
    result = run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
    )

    assert result.stop_reason is StopReason.ERROR
    assert result.error == "provider rate limit reached; retry after 5s"
    assert result.iteration_count == 0


class _LimitedThenOkNativeAdapter(FakeAdapter):
    """Drives a native loop that reports a usage limit, then succeeds on retry."""

    def __init__(self, *, limited: int) -> None:
        super().__init__(supports_native=True)
        self._limited = limited
        self.native_calls = 0

    def drive_native_loop(self, goal, verify, max_iterations, workdir):
        self.native_calls += 1
        if self.native_calls <= self._limited:
            return IterationResult(
                transcript="rate limited", ok=False, error="provider rate limit reached; retry after 5s"
            )
        return IterationResult(transcript="native done", ok=True)


def test_delegate_loop_waits_out_usage_limit_then_succeeds(workdir):
    adapter = _LimitedThenOkNativeAdapter(limited=1)
    waits: list[float] = []
    result = run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
        resume_on_limit=True,
        sleep=waits.append,
    )

    assert result.stop_reason is StopReason.SUCCESS
    assert result.mode == "delegate"
    assert adapter.native_calls == 2  # retried once after the limit
    assert waits == [5.0]


def test_delegate_loop_limit_is_terminal_without_resume(workdir):
    adapter = _LimitedThenOkNativeAdapter(limited=1)
    result = run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
    )

    assert result.stop_reason is StopReason.ERROR
    assert adapter.native_calls == 1


class _AlwaysLimitedAdapter(FakeAdapter):
    """Reports a usage limit on every call — a stuck account or a misclassification."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run_iteration(self, goal, context, workdir, model=None):
        self.calls += 1
        return IterationResult(
            transcript="rate limited", ok=False, error="provider rate limit reached; retry after 1s"
        )


def test_supply_loop_stops_after_max_resumes(workdir):
    adapter = _AlwaysLimitedAdapter()
    waits: list[float] = []
    result = run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
        resume_on_limit=True,
        limit_max_resumes=2,
        sleep=waits.append,
    )

    assert result.stop_reason is StopReason.ERROR
    assert "provider rate limit reached" in (result.error or "")
    assert len(waits) == 2  # two resumes, then give up rather than loop forever
    assert adapter.calls == 3  # initial attempt + two retries


def test_supply_loop_backs_off_when_no_reset_named(workdir):
    adapter = _LimitedThenOkAdapter(limited=2, retry="")
    waits: list[float] = []
    run_loop(
        "fix it",
        adapter,
        _config(),
        workdir,
        verify_fn=make_verify(pass_on=1),
        checkpointer=Checkpointer(workdir, enabled=False),
        resume_on_limit=True,
        limit_backoff_seconds=10.0,
        sleep=waits.append,
    )

    assert waits == [10.0, 20.0]  # exponential back-off within one iteration slot


def test_hits_iteration_cap(workdir):
    adapter = FakeAdapter()
    result = _run(adapter, _config(max_iterations=3), workdir, pass_on=99)
    assert result.stop_reason is StopReason.ITERATION_CAP
    assert result.iteration_count == 3


def test_context_carries_verify_output_forward(workdir):
    adapter = FakeAdapter()
    _run(adapter, _config(), workdir, pass_on=3)
    # First iteration has empty context; later ones carry the failure forward (B2).
    assert adapter.contexts[0] == ""
    assert "test_foo.py" in adapter.contexts[1]


def test_continuation_context_keeps_short_output_intact():
    verify = VerifyResult(passed=False, exit_code=1, output="short failure")
    context = _continuation_context(verify)
    assert "short failure" in context
    assert "truncated" not in context


def test_continuation_context_marks_truncated_output():
    overflow = 500
    output = "X" * (_CONTEXT_OUTPUT_LIMIT + overflow)
    verify = VerifyResult(passed=False, exit_code=1, output=output)
    context = _continuation_context(verify)
    # The dropped early detail is no longer invisible: a marker names the count.
    assert f"[...{overflow} earlier characters truncated...]" in context
    # The tail is preserved; only the overflow prefix is dropped.
    assert context.endswith("X" * _CONTEXT_OUTPUT_LIMIT)


def test_native_delegates_then_verifies(workdir):
    adapter = FakeAdapter(supports_native=True)
    result = run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(1),  # native loop "succeeds", our verify confirms
        checkpointer=Checkpointer(workdir, enabled=False),
    )
    assert adapter.native_runs == 1
    assert adapter.iterations_run == 0  # delegated, not supplied
    assert result.mode == "delegate"
    assert result.stop_reason is StopReason.SUCCESS


def test_native_records_failure_when_verify_still_fails(workdir):
    adapter = FakeAdapter(supports_native=True)
    result = run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(99),  # native loop ran but verify (our contract) still fails
        checkpointer=Checkpointer(workdir, enabled=False),
    )
    assert result.mode == "delegate"
    assert not result.passed


def test_native_ignored_when_unsupported(workdir):
    adapter = FakeAdapter(supports_native=False)
    result = run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,  # asked for native, but adapter can't → supply instead
        verify_fn=make_verify(1),
        checkpointer=Checkpointer(workdir, enabled=False),
    )
    assert result.mode == "supply"
    assert adapter.iterations_run == 1


def test_missing_verify_refuses_to_loop(workdir):
    adapter = FakeAdapter()
    result = run_loop("x", adapter, _config(verify=None), workdir)
    assert result.stop_reason is StopReason.NO_VERIFY
    assert adapter.iterations_run == 0


def test_unavailable_agent_stops_cleanly(workdir):
    adapter = FakeAdapter(available=False)
    result = run_loop("x", adapter, _config(), workdir)
    assert result.stop_reason is StopReason.AGENT_UNAVAILABLE


def test_supply_agent_failure_is_not_masked_by_green_verify(workdir):
    adapter = FakeAdapter(ok=False)

    result = _run(adapter, _config(), workdir, pass_on=1)

    assert result.stop_reason is StopReason.ERROR
    assert result.passed is False
    assert result.error == "provider credits exhausted"
    assert result.iteration_count == 0


def test_delegate_agent_failure_is_not_masked_by_green_verify(workdir):
    adapter = FakeAdapter(supports_native=True, ok=False)

    result = run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(1),
        checkpointer=Checkpointer(workdir, enabled=False),
    )

    assert result.stop_reason is StopReason.ERROR
    assert result.passed is False
    assert result.error == "provider credits exhausted"
    assert result.iteration_count == 0


def test_on_iteration_callback_called_per_iteration(workdir):
    adapter = FakeAdapter()
    seen: list = []

    run_loop(
        "fix tests",
        adapter,
        _config(),
        workdir,
        verify_fn=make_verify(2),
        checkpointer=Checkpointer(workdir, enabled=False),
        on_iteration=seen.append,
    )

    assert len(seen) == 2  # pass_on=2 → 2 iterations
    assert all(hasattr(r, "verify") for r in seen)
    assert seen[-1].verify.passed  # last record is the passing one


def test_on_iteration_callback_called_in_delegate_path(workdir):
    adapter = FakeAdapter(supports_native=True)
    seen: list = []

    run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(1),
        checkpointer=Checkpointer(workdir, enabled=False),
        on_iteration=seen.append,
    )

    assert len(seen) == 1  # one verify record from the delegate path
    assert seen[0].verify.passed
