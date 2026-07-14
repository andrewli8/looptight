"""Deterministic, model-free evaluation of a generated idea batch.

Idea generation is non-deterministic: the host agent invents the tasks and
looptight makes no model call. But the *grounding* of a generated batch is
checkable without a model. Does each task's ``Evidence:`` anchor resolve to a real
repository file? Does the batch stay within the prompt's 1-6 bound? Does it span
several areas of the codebase rather than fixating on one (the flexibility
dimension of divergent thinking, Guilford 1956)? Are the tasks distinct rather
than near-duplicates (the LLM "diversity ceiling", Si et al. 2024)? Scoring those
properties turns "did the new generation prompt help?" from an assertion into a
measurement, and gives a hard guard against grounded-looking busywork.

Pure functions over Candidates and the working tree. No model or network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .discovery import Candidate, from_status_next
from .grounding import evidence_refs as _evidence_refs_text
from .grounding import is_grounded as _is_grounded_text
from .idea_identity import idea_id

__all__ = [
    "evidence_refs", "is_grounded", "BatchScore", "score_batch", "score_status_next",
]

_MIN_TASKS = 1
_MAX_TASKS = 6


def evidence_refs(candidate: Candidate) -> list[str]:
    """Every ``Evidence:`` anchor named in a candidate's text (``path`` or ``path:line``)."""
    return _evidence_refs_text(candidate.detail or "")


def is_grounded(root: Path, candidate: Candidate) -> bool:
    """A task is grounded when it names at least one evidence anchor and every one
    of them resolves to an existing repository file. This is the deterministic guard
    against grounded-looking tasks whose evidence is invented."""
    return _is_grounded_text(root, candidate.detail or "")


def _area(candidate: Candidate) -> str:
    """The codebase area a task targets, for the flexibility (category-spread) metric:
    the parent directory of its first evidence path, else the path or the source."""
    refs = evidence_refs(candidate)
    if refs:
        path_text = refs[0].rsplit(":", 1)[0] if ":" in refs[0] else refs[0]
        parent = Path(path_text).parent.as_posix()
        return parent if parent and parent != "." else "."
    return candidate.source


@dataclass(frozen=True)
class BatchScore:
    """Deterministic grounding metrics for one generated batch."""

    size: int
    grounded: int       # tasks whose evidence anchors all resolve to real files
    flexibility: int    # distinct codebase areas the batch touches (Guilford)
    distinct: int       # distinct idea identities in the batch (intra-batch dedup)
    bounded: bool       # batch size within the prompt's 1-6 bound

    @property
    def groundedness(self) -> float:
        """Fraction of the batch that is grounded; 0.0 for an empty batch."""
        return self.grounded / self.size if self.size else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "grounded": self.grounded,
            "groundedness": round(self.groundedness, 3),
            "flexibility": self.flexibility,
            "distinct": self.distinct,
            "bounded": self.bounded,
        }


def score_batch(root: Path, candidates: list[Candidate]) -> BatchScore:
    """Score a generated batch on deterministic, model-free grounding metrics."""
    grounded = sum(1 for candidate in candidates if is_grounded(root, candidate))
    areas = {_area(candidate) for candidate in candidates}
    distinct = {idea_id(candidate) for candidate in candidates}
    size = len(candidates)
    return BatchScore(
        size=size,
        grounded=grounded,
        flexibility=len(areas),
        distinct=len(distinct),
        bounded=_MIN_TASKS <= size <= _MAX_TASKS,
    )


def score_status_next(root: Path) -> BatchScore:
    """Score whatever the host has generated into docs/STATUS.md's ``## Next``.

    Reads the *uncapped* (``cap=None``) and *unfiltered* (``enforce_truthful_evidence=False``)
    Next section, so the score reflects the raw batch the host wrote — its true size (an
    over-budget batch reports ``bounded=False``) and its real groundedness (``score_batch``
    counts which items' evidence resolves). Pre-filtering ungrounded items here would force
    ``grounded == size`` (groundedness a useless 1.0) and hide over-generation, defeating the
    point of the feedback signal.
    """
    return score_batch(
        root, from_status_next(root, cap=None, enforce_truthful_evidence=False)
    )
