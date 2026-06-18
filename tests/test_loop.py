"""End-to-end loop behaviour with injected fakes (B1, B2, C1, D1)."""

from __future__ import annotations

from looptight.checkpoint import Checkpointer
from looptight.config import Config
from looptight.lessons import LessonStore
from looptight.loop import run_loop
from looptight.types import StopReason

from conftest import FakeAdapter, make_verify


def _config(**kw) -> Config:
    base = dict(verify="pytest -q", agent="fake", max_iterations=5, budget_usd=1.0, reflect=True)
    base.update(kw)
    return Config(**base)


def _run(adapter, config, workdir, *, pass_on, store=None):
    return run_loop(
        "fix the failing tests",
        adapter,
        config,
        workdir,
        verify_fn=make_verify(pass_on),
        checkpointer=Checkpointer(workdir, enabled=False),
        store=store,
    )


def test_stops_on_first_pass(workdir):
    adapter = FakeAdapter()
    result = _run(adapter, _config(), workdir, pass_on=2)
    assert result.stop_reason is StopReason.SUCCESS
    assert result.passed
    assert result.iteration_count == 2
    assert adapter.iterations_run == 2


def test_hits_iteration_cap(workdir):
    adapter = FakeAdapter()
    result = _run(adapter, _config(max_iterations=3), workdir, pass_on=99)
    assert result.stop_reason is StopReason.ITERATION_CAP
    assert result.iteration_count == 3


def test_stops_at_budget_ceiling(workdir):
    adapter = FakeAdapter(cost=0.6)
    result = _run(adapter, _config(max_iterations=10, budget_usd=1.0), workdir, pass_on=99)
    assert result.stop_reason is StopReason.BUDGET_EXCEEDED
    # Two iterations spend $1.20, crossing the $1.00 ceiling.
    assert result.iteration_count == 2
    assert result.total_cost_usd >= 1.0


def test_writes_lesson_after_failed_then_fixed(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    adapter = FakeAdapter()
    result = _run(adapter, _config(), workdir, pass_on=2, store=store)
    assert result.passed
    assert result.lesson is not None
    saved = store.list()
    assert len(saved) == 1
    assert "client.py" in saved[0].text


def test_no_lesson_when_reflect_disabled(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    adapter = FakeAdapter()
    result = _run(adapter, _config(reflect=False), workdir, pass_on=2, store=store)
    assert result.lesson is None
    assert store.list() == []


def test_no_lesson_when_clean_first_pass(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    adapter = FakeAdapter()
    result = _run(adapter, _config(), workdir, pass_on=1, store=store)
    assert result.passed
    assert result.lesson is None  # no failure to learn from


def test_vague_reflection_is_dropped(workdir):
    store = LessonStore(workdir / "CLAUDE.md")
    adapter = FakeAdapter(reflect_text="the test failed")  # generic → discarded
    result = _run(adapter, _config(), workdir, pass_on=2, store=store)
    assert result.lesson is None
    assert store.list() == []


def test_context_carries_verify_output_forward(workdir):
    adapter = FakeAdapter()
    _run(adapter, _config(), workdir, pass_on=3)
    # First iteration has empty context; later ones carry the failure forward (B2).
    assert adapter.contexts[0] == ""
    assert "test_foo.py" in adapter.contexts[1]


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
    store = LessonStore(workdir / "CLAUDE.md")
    adapter = FakeAdapter(supports_native=True)
    result = run_loop(
        "do it",
        adapter,
        _config(),
        workdir,
        native=True,
        verify_fn=make_verify(99),  # native loop ran but verify (our contract) still fails
        checkpointer=Checkpointer(workdir, enabled=False),
        store=store,
    )
    assert result.mode == "delegate"
    assert not result.passed
    assert result.lesson is not None  # we still reflect on a delegated failure


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
