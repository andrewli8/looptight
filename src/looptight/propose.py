"""Task proposal — compose discovery and ranking into a candidate list.

`propose` is the grounded half of "what to work on": it discovers verifiable
signals (``discovery.py``), dedupes and ranks them (``ranking.py``), and returns
the top candidates. It runs no agent, spends no tokens, and writes nothing.

Discovery and ranking live in their own modules so each stays a single concern;
this module only wires them together and re-exports :class:`Candidate`, the
public type its result is made of.
"""

from __future__ import annotations

from pathlib import Path

from .discovery import Candidate, discover
from .ranking import dedupe, rank

__all__ = ["Candidate", "propose"]


def propose(root: Path, *, limit: int = 10) -> list[Candidate]:
    """Scan all signals, dedupe, rank, and return the top ``limit`` candidates."""
    ranked = rank(dedupe(discover(root)))
    return ranked[:limit] if limit and limit > 0 else ranked
