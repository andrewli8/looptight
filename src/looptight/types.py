"""Shared, immutable data types.

These are the contract between the loop, the adapters, verify, reflection, and
the summary. Everything returns new objects; nothing here is mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum


class StopReason(str, Enum):
    """Why a run ended. Drives the final line of the summary."""

    SUCCESS = "success"
    ITERATION_CAP = "iteration_cap"
    BUDGET_EXCEEDED = "budget_exceeded"
    NO_PROGRESS = "no_progress"  # stalled after real progress — cut losses
    ESCALATED = "escalated"  # never moved the needle — a human should look
    NO_VERIFY = "no_verify"
    AGENT_UNAVAILABLE = "agent_unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class VerifyResult:
    """The ground-truth oracle's verdict for one check (B3)."""

    passed: bool
    exit_code: int
    output: str = ""
    score: float | None = None
    duration_s: float = 0.0
    error: str | None = None

    def __post_init__(self) -> None:
        if self.passed != (self.exit_code == 0):
            raise ValueError("verify pass state must match exit code zero")
        if self.passed and self.error:
            raise ValueError("a passing verify result cannot contain an execution error")

    @property
    def status(self) -> str:
        """Stable verdict for automation: pass, fail, timeout, or error."""
        if self.passed:
            return "pass"
        if self.error == "timeout":
            return "timeout"
        if self.error:
            return "error"
        return "fail"

    def short(self) -> str:
        """A compact, gif-able status fragment, e.g. ``PASS`` or ``FAIL``."""
        label = "PASS" if self.passed else "FAIL"
        if self.score is not None:
            return f"{label} (score {self.score:g})"
        return label


@dataclass(frozen=True)
class IterationResult:
    """What an adapter reports back after running one iteration (supply mode)."""

    transcript: str = ""
    cost_usd: float = 0.0
    ok: bool = True
    error: str | None = None


@dataclass(frozen=True)
class IterationRecord:
    """One row of the run summary."""

    number: int
    verify: VerifyResult
    cost_usd: float
    checkpoint: str | None = None

    def line(self) -> str:
        """The gif-able ``iteration N → verify: PASS/FAIL`` line (E2)."""
        return f"iteration {self.number} → verify: {self.verify.short()}"


@dataclass(frozen=True)
class Lesson:
    """A durable, scoped lesson written to the agent's memory file (C1–C4)."""

    text: str
    scope: str = "*"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    @property
    def key(self) -> str:
        """Normalized dedupe key (C4): scope + lowercased, whitespace-collapsed text."""
        normalized = " ".join(self.text.lower().split())
        return f"{self.scope}::{normalized}"

    def render(self) -> str:
        """One markdown bullet for the memory file."""
        prefix = "" if self.scope in ("*", "") else f"(scope: {self.scope}) "
        return f"- [{self.created_at}] {prefix}{self.text}"


@dataclass(frozen=True)
class RunResult:
    """The outcome of a full run, delegated or supplied. Backend-neutral (B4)."""

    goal: str
    agent: str
    mode: str  # "supply" | "delegate"
    stop_reason: StopReason
    iterations: tuple[IterationRecord, ...] = ()
    total_cost_usd: float = 0.0
    reports_cost_usd: bool = True  # False when the agent bills but reports no USD
    lesson: Lesson | None = None
    diffstat: str = ""
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.stop_reason is StopReason.SUCCESS

    @property
    def iteration_count(self) -> int:
        return len(self.iterations)

    def with_lesson(self, lesson: Lesson | None) -> "RunResult":
        return replace(self, lesson=lesson)
