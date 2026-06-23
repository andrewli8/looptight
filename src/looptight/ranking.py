"""Proposal ranking: order and dedupe discovered candidates.

The ranking half of task generation takes the candidates produced by
``discovery.py`` and decides *which to run first*. It is a transparent
source-priority heuristic, labeled as one, not a claim of optimal ordering — a
passing verifier, not this sort, is what authorizes any work (see docs/SPEC.md).
"""

from __future__ import annotations

from .discovery import Candidate
from .experience import Model, reweight_factor

# Source-priority weights for ranking. Higher runs first. This is a transparent
# heuristic, not a validated ordering (see docs/SPEC.md).
_SOURCE_WEIGHT = {
    "verify": 100,  # reserved for a future failing-verify extractor
    "types": 80,    # reserved for a future mypy extractor
    "task-file": 70,    # human-curated intent outranks automated signals
    "status-next": 65,  # human/planner-curated plan; kept just below task-file
    "lint": 60,
    "skipped-test": 40,
    "todo": 20,
}


def _normalized(title: str) -> str:
    return " ".join(title.lower().split())


_REWEIGHT_LO = 0.5
_REWEIGHT_HI = 1.08  # keep a boosted automated source below the next curated tier

# Human-authored sources whose relative ordering must never be inverted by
# learned damping. A failed task-file or status-next idea should still run
# before any automated signal; the verifier — not ranking — is the quality gate.
_CURATED_SOURCES = {"task-file", "status-next"}


def rank(candidates: list[Candidate]) -> list[Candidate]:
    """Stable sort by source priority (descending). Heuristic, not validated."""
    scored = [
        Candidate(**{**c.__dict__, "score": float(_SOURCE_WEIGHT.get(c.source, 0))})
        for c in candidates
    ]
    return sorted(scored, key=lambda c: c.score, reverse=True)


def rank_with_model(candidates: list[Candidate], model: Model) -> list[Candidate]:
    """Stable sort by source weight, scaled by clamped category yield (automated
    sources only). Curated sources keep their base weight so learned damping can
    never reorder human-authored intent below an automated signal."""
    scored = []
    for c in candidates:
        base = float(_SOURCE_WEIGHT.get(c.source, 0))
        factor = (
            1.0 if c.source in _CURATED_SOURCES
            else reweight_factor(c.source, model, lo=_REWEIGHT_LO, hi=_REWEIGHT_HI)
        )
        scored.append(Candidate(**{**c.__dict__, "score": base * factor}))
    return sorted(scored, key=lambda c: c.score, reverse=True)


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """Drop later candidates with an already-seen (location, normalized title)."""
    seen: set[tuple[str | None, str]] = set()
    out: list[Candidate] = []
    for c in candidates:
        key = (c.location, _normalized(c.title))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
