"""Value-aware stopping — the metacognitive controller (Phase 1).

The plain supply loop grinds to the iteration cap even when it stopped making
progress three iterations ago, which is exactly where tokens get wasted. This
module adds the cheap half of a monitor->control loop: after each failed verify,
look at the *trajectory* of the verify signal and decide whether another
iteration is worth it.

Grounding: rational metareasoning / value-of-computation (Russell & Wefald; Hay
& Russell; Lieder & Griffiths) — keep computing only while the expected gain
beats the cost. Exact value-of-computation is intractable, so this is the cheap
myopic approximation the literature prescribes: a few comparisons over a signal
looptight already collects. No extra model calls, no tokens.

It deliberately does not try to *pick* a winning attempt from confidence (a
known failure mode); ``verify`` stays the oracle for that. The controller only
gates whether to keep iterating, and distinguishes "made progress then stalled"
(stop, cut losses) from "never moved the needle at all" (escalate to a human).
"""

from __future__ import annotations

import re
from enum import Enum

from .types import Escalation, IterationRecord, StopReason, VerifyResult

# Counts of things that are wrong, as reported by common test/lint runners. We
# turn these into a "higher is better" progress number by negating the total.
_FAIL_RE = re.compile(r"(\d+)\s+(?:failed|failing|errors?)", re.IGNORECASE)


class Decision(str, Enum):
    """What the controller advises after a failed iteration."""

    CONTINUE = "continue"
    STOP_NO_PROGRESS = "stop_no_progress"  # improved, then plateaued — cut losses
    ESCALATE = "escalate"  # never improved — a human should look


def progress_signal(verify: VerifyResult) -> float | None:
    """A cheap "closer to passing" number from a verify result; higher is better.

    Prefers an explicit ``SCORE:`` (already parsed onto ``score``). Otherwise
    counts failures/errors in the output and negates them, so fewer failures
    reads as more progress. Returns None when nothing is parseable, which the
    controller treats as "no signal, keep going".
    """
    if verify.passed:
        return None
    if verify.score is not None:
        return verify.score
    counts = [int(n) for n in _FAIL_RE.findall(verify.output or "")]
    if not counts:
        return None
    return -float(sum(counts))


def assess(history: list[float | None], patience: int) -> Decision:
    """Decide whether to keep iterating, given the progress signal so far.

    ``history`` is the per-iteration progress (most recent last; None = no
    signal). ``patience`` is how many trailing iterations of no improvement to
    tolerate; 0 disables the controller entirely (legacy run-to-cap behaviour).
    """
    if patience <= 0:
        return Decision.CONTINUE

    known = [p for p in history if p is not None]
    if len(known) < patience + 1:
        return Decision.CONTINUE  # not enough signal to call a stall yet

    prior_best = max(known[:-patience])
    recent_best = max(known[-patience:])
    if recent_best > prior_best:
        return Decision.CONTINUE  # still improving

    # Stalled. If we ever beat the starting point, we made real progress and are
    # now in diminishing returns; otherwise the agent never moved the needle.
    if prior_best > known[0]:
        return Decision.STOP_NO_PROGRESS
    return Decision.ESCALATE


# --- escalation evidence ---------------------------------------------------
#
# When the controller stops a run early, surface *why*: the failures that never
# cleared across the attempts, plus a one-line, human-readable summary. Pure and
# runner-agnostic — it reads the verify output the loop already collected.

MAX_PERSISTENT_FAILURES = 10
MAX_FAILURE_LINE = 200

# A line worth showing as failure evidence, across pytest/unittest, jest/vitest,
# go test, and TAP. Broad on purpose; the cross-iteration intersection and the
# final-iteration fallback keep stray matches from misleading anyone.
_FAILURE_LINE_RE = re.compile(
    r"(FAILED|FAIL:|--- FAIL|AssertionError|Traceback|not ok|^\s*[✗✕×])",
    re.IGNORECASE,
)
# A run tally ("=== 2 failed, 18 passed in 0.4s ===") is a count, not a failure
# identity — it is already captured by the trajectory, so it is not evidence.
_TALLY_RE = re.compile(r"^[=\s]*\d+\s+(?:failed|passed|errors?|skipped)\b", re.IGNORECASE)
# Volatile fragments neutralized so the same failure matches across runs.
_HEX_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
_IN_SECONDS_RE = re.compile(r"\bin\s+\d+(?:\.\d+)?\s*m?s\b", re.IGNORECASE)
_DURATION_RE = re.compile(r"\s*\(?\b\d+(?:\.\d+)?\s*m?s\)?\s*$", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _normalize_failure(line: str) -> str:
    line = _HEX_ADDR_RE.sub("0xADDR", line.strip())
    line = _IN_SECONDS_RE.sub("in Ns", line)
    line = _DURATION_RE.sub("", line)
    return _WS_RE.sub(" ", line).strip()[:MAX_FAILURE_LINE]


def _failure_lines(output: str) -> set[str]:
    """Normalized failure-shaped lines from one verify output."""
    lines = set()
    for raw in (output or "").splitlines():
        if _FAILURE_LINE_RE.search(raw) and not _TALLY_RE.match(raw.strip()):
            normalized = _normalize_failure(raw)
            if normalized:
                lines.add(normalized)
    return lines


def persistent_from_sets(failure_sets: list[set[str]]) -> tuple[tuple[str, ...], bool]:
    """The failures behind an early stop, as ``(lines, persisted)``, from
    pre-extracted per-iteration failure sets (so both the in-memory run loop and
    the cross-process session-native path share one intersection).

    ``persisted`` is True when the lines appeared in *every* iteration (a real
    "never cleared"). When no failure held across all iterations, fall back to the
    final iteration's failures with ``persisted=False``. Empty when nothing parses.
    """
    if not failure_sets:
        return (), True
    common = set.intersection(*failure_sets)
    if common:
        return tuple(sorted(common)), True
    final = failure_sets[-1]
    if final:
        return tuple(sorted(final)), False
    return (), True


def persistent_failures(records: list[IterationRecord]) -> tuple[tuple[str, ...], bool]:
    """The failures behind an early stop, from in-memory iteration records."""
    return persistent_from_sets([_failure_lines(record.verify.output) for record in records])


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _summarize(kind: str, total: int, persisted: bool, iterations: int) -> str:
    tries = "1 try" if iterations == 1 else f"{iterations} tries"
    shape = (
        f"No progress across {tries}."
        if kind == "escalated"
        else f"Improved, then stalled across {tries}."
    )
    if total == 0:
        return f"{shape} No specific failures parsed; check the final output."
    if persisted:
        return f"{shape} {_plural(total, 'failure')} never cleared."
    return f"{shape} Showing the latest {_plural(total, 'failure')}; none held across every try."


def escalation_from_signals(
    history: list[float | None], failure_sets: list[set[str]], stop_reason: StopReason
) -> Escalation:
    """Assemble the escalation report from a trajectory and per-iteration failure
    sets — the form available across separate processes (session-native path)."""
    kind = "escalated" if stop_reason is StopReason.ESCALATED else "no_progress"
    all_failures, persisted = persistent_from_sets(failure_sets)
    total = len(all_failures)
    iterations = len(failure_sets)
    return Escalation(
        kind=kind,
        iterations=iterations,
        trajectory=tuple(history),
        failures=all_failures[:MAX_PERSISTENT_FAILURES],
        summary=_summarize(kind, total, persisted, iterations),
        persisted=persisted,
        total_failures=total,
    )


def build_escalation(
    records: list[IterationRecord], history: list[float | None], stop_reason: StopReason
) -> Escalation:
    """Assemble the escalation report from in-memory iteration records (run loop)."""
    return escalation_from_signals(
        history, [_failure_lines(record.verify.output) for record in records], stop_reason
    )
