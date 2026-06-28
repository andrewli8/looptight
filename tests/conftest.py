"""Shared test doubles.

The loop is built to be driven by injected pieces, so these fakes stand in for a
real agent, a real verify command, and git — letting us test the control flow
deterministically and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from looptight.adapters.base import Adapter
from looptight.types import IterationResult, VerifyResult


class FakeAdapter(Adapter):
    """A fake adapter that records calls and never touches the network.

    It can supply the loop (always) and, when ``supports_native=True``, also
    drive a fake native loop — so one double covers both paths.
    """

    name = "fake"
    memory_filename = "CLAUDE.md"

    def __init__(
        self,
        *,
        available: bool = True,
        supports_native: bool = False,
        ok: bool = True,
    ) -> None:
        self.available = available
        self.supports_native_loop = supports_native
        self.ok = ok
        self.iterations_run = 0
        self.native_runs = 0
        self.contexts: list[str] = []

    def is_available(self) -> bool:
        return self.available

    def run_iteration(self, goal: str, context: str, workdir: Path, model: str | None = None) -> IterationResult:
        self.iterations_run += 1
        self.contexts.append(context)
        return IterationResult(
            transcript=f"attempt {self.iterations_run}",
            ok=self.ok,
            error=None if self.ok else "provider credits exhausted",
        )

    def drive_native_loop(
        self, goal, verify, max_iterations, workdir, model=None
    ) -> IterationResult:
        self.native_runs += 1
        return IterationResult(
            transcript="native loop done",
            ok=self.ok,
            error=None if self.ok else "provider credits exhausted",
        )

def make_verify(pass_on: int):
    """Return a verify_fn that passes on its ``pass_on``-th call, fails before."""
    state = {"n": 0}

    def verify_fn(command: str, cwd: Path) -> VerifyResult:
        state["n"] += 1
        passed = state["n"] >= pass_on
        return VerifyResult(
            passed=passed,
            exit_code=0 if passed else 1,
            output="" if passed else "1 failing test in test_foo.py: AssertionError",
        )

    return verify_fn


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path
