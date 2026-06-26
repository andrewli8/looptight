"""Shared, immutable data types.

These are the contract between the loop, adapters, verifier, and summary.
Everything returns new objects; nothing here is mutated in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StopReason(str, Enum):
    """Why a run ended. Drives the final line of the summary."""

    SUCCESS = "success"
    ITERATION_CAP = "iteration_cap"
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
    ok: bool = True
    error: str | None = None
    returncode: int | None = None  # provider process exit code (124 = timeout)


@dataclass(frozen=True)
class IterationRecord:
    """One row of the run summary."""

    number: int
    verify: VerifyResult
    checkpoint: str | None = None

    def line(self) -> str:
        """The gif-able ``iteration N → verify: PASS/FAIL`` line (E2)."""
        return f"iteration {self.number} → verify: {self.verify.short()}"


@dataclass(frozen=True)
class Escalation:
    """Why the controller stopped a run early, with the evidence behind it.

    Attached to a ``RunResult`` only on an early stop (escalated / no_progress).
    ``persisted`` is False when ``failures`` is a final-iteration fallback rather
    than a true "present in every iteration" set."""

    kind: str  # "escalated" | "no_progress"
    iterations: int
    trajectory: tuple[float | None, ...]
    failures: tuple[str, ...]
    summary: str
    persisted: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "iterations": self.iterations,
            "trajectory": list(self.trajectory),
            "failures": list(self.failures),
            "summary": self.summary,
            "persisted": self.persisted,
        }


@dataclass(frozen=True)
class RunResult:
    """The outcome of a full run, delegated or supplied. Backend-neutral (B4)."""

    goal: str
    agent: str
    mode: str  # "supply" | "delegate"
    stop_reason: StopReason
    iterations: tuple[IterationRecord, ...] = ()
    diffstat: str = ""
    error: str | None = None
    returncode: int | None = None  # provider process exit code from a failed iteration
    escalation: Escalation | None = None

    @property
    def passed(self) -> bool:
        return self.stop_reason is StopReason.SUCCESS

    def as_dict(self) -> dict[str, object]:
        """Bounded, versioned view for ``run --json``. Per-iteration output is
        omitted (unbounded); the escalation distills the persistent failures."""
        return {
            "command": "run",
            "schema_version": 1,
            "goal": self.goal,
            "agent": self.agent,
            "mode": self.mode,
            "stop_reason": self.stop_reason.value,
            "passed": self.passed,
            "iterations": [
                {
                    "number": record.number,
                    "passed": record.verify.passed,
                    "status": record.verify.status,
                    "exit_code": record.verify.exit_code,
                    "score": record.verify.score,
                }
                for record in self.iterations
            ],
            "diffstat": self.diffstat,
            "error": self.error,
            "returncode": self.returncode,
            "escalation": self.escalation.as_dict() if self.escalation else None,
        }

    @property
    def iteration_count(self) -> int:
        return len(self.iterations)
