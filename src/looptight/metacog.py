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

from .types import VerifyResult

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
