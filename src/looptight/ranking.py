"""Proposal ranking: order and dedupe discovered candidates.

The ranking half of task generation takes the candidates produced by
``discovery.py`` and decides *which to run first*. It is a transparent
source-priority heuristic, labeled as one, not a claim of optimal ordering — a
passing verifier, not this sort, is what authorizes any work (see docs/SPEC.md).
"""

from __future__ import annotations

from .discovery import Candidate

# Source-priority weights for ranking. Higher runs first. This is a transparent
# heuristic, not a validated ordering (see docs/SPEC.md).
_SOURCE_WEIGHT = {
    "verify": 100,  # reserved for a future failing-verify extractor
    "types": 80,    # reserved for a future mypy extractor
    "lint": 60,
    "skipped-test": 40,
    "todo": 20,
    "status-next": 10,
}


def _normalized(title: str) -> str:
    return " ".join(title.lower().split())


def rank(candidates: list[Candidate]) -> list[Candidate]:
    """Stable sort by source priority (descending). Heuristic, not validated."""
    scored = [
        Candidate(**{**c.__dict__, "score": float(_SOURCE_WEIGHT.get(c.source, 0))})
        for c in candidates
    ]
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
