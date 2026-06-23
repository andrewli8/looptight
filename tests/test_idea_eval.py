"""Deterministic evaluation of generated idea batches.

Idea generation is non-deterministic, but its grounding is checkable without a
model. These tests prove the scorer separates a well-grounded, diverse, bounded
batch from a batch of grounded-looking busywork (fabricated evidence, fixated on
one area, oversized, duplicated).
"""

from __future__ import annotations

from pathlib import Path

from looptight.discovery import Candidate
from looptight.idea_eval import (
    BatchScore,
    evidence_refs,
    is_grounded,
    score_batch,
    score_status_next,
)


def _candidate(title: str, detail: str) -> Candidate:
    return Candidate(
        title=title,
        source="status-next",
        location="docs/STATUS.md:5",
        suggested_verify=None,
        score=0.0,
        detail=detail,
        acceptance="passes verification.",
    )


def _repo_with_files(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "a.py").write_text("# a\n")
    (root / "src" / "b.py").write_text("# b\n")
    (root / "tests" / "test_c.py").write_text("# c\n")


def test_evidence_refs_parses_each_marker():
    cand = _candidate(
        "Do the thing",
        "Do the thing. Evidence: src/a.py:10; Evidence: tests/test_c.py:3; Acceptance: x",
    )
    assert evidence_refs(cand) == ["src/a.py:10", "tests/test_c.py:3"]


def test_is_grounded_true_only_when_every_anchor_resolves(tmp_path):
    _repo_with_files(tmp_path)
    real = _candidate("Harden a", "Harden a. Evidence: src/a.py:10; Acceptance: x")
    fabricated = _candidate("Do x", "Do x. Evidence: src/made_up.py:1; Acceptance: x")
    no_evidence = _candidate("Refactor", "Refactor everything. Acceptance: x")
    partial = _candidate(
        "Mix", "Mix. Evidence: src/a.py:1; Evidence: src/ghost.py:2; Acceptance: x"
    )
    assert is_grounded(tmp_path, real) is True
    assert is_grounded(tmp_path, fabricated) is False  # path does not exist
    assert is_grounded(tmp_path, no_evidence) is False  # names no anchor at all
    assert is_grounded(tmp_path, partial) is False  # one of two anchors is invented


def test_is_grounded_rejects_escaping_or_absolute_paths(tmp_path):
    _repo_with_files(tmp_path)
    escaping = _candidate("Esc", "Esc. Evidence: ../secrets.py:1; Acceptance: x")
    absolute = _candidate("Abs", "Abs. Evidence: /etc/passwd:1; Acceptance: x")
    assert is_grounded(tmp_path, escaping) is False
    assert is_grounded(tmp_path, absolute) is False


def test_score_batch_rewards_a_grounded_diverse_bounded_batch(tmp_path):
    _repo_with_files(tmp_path)
    good = [
        _candidate("Harden a", "Harden a. Evidence: src/a.py:10; Acceptance: x"),
        _candidate("Cover c", "Cover c. Evidence: tests/test_c.py:3; Acceptance: x"),
        _candidate("Fix b", "Fix b. Evidence: src/b.py:1; Acceptance: x"),
    ]
    score = score_batch(tmp_path, good)
    assert score == BatchScore(size=3, grounded=3, flexibility=2, distinct=3, bounded=True)
    assert score.groundedness == 1.0


def test_score_batch_penalizes_busywork(tmp_path):
    _repo_with_files(tmp_path)
    bad = [
        _candidate("Do x", "Do x. Evidence: src/made_up.py:1; Acceptance: x"),
        _candidate("Refactor", "Refactor everything. Acceptance: x"),  # no evidence
        _candidate("Do x", "Do x. Evidence: src/made_up.py:1; Acceptance: x"),  # duplicate
    ]
    score = score_batch(tmp_path, bad)
    assert score.grounded == 0
    assert score.groundedness == 0.0
    assert score.distinct == 2  # the two "Do x" items collapse to one identity


def test_score_batch_flags_an_unbounded_batch(tmp_path):
    _repo_with_files(tmp_path)
    oversized = [
        _candidate(f"Task {i}", f"Task {i}. Evidence: src/a.py:{i}; Acceptance: x")
        for i in range(7)
    ]
    assert score_batch(tmp_path, oversized).bounded is False
    assert score_batch(tmp_path, []).bounded is False  # empty is not a valid batch


def test_good_batch_outscores_busywork_on_groundedness(tmp_path):
    # The discriminator the eval exists for: a grounded batch must score strictly
    # higher on groundedness than plausible-looking busywork.
    _repo_with_files(tmp_path)
    good = [_candidate("Harden a", "Harden a. Evidence: src/a.py:10; Acceptance: x")]
    busywork = [_candidate("Do x", "Do x. Evidence: src/ghost.py:1; Acceptance: x")]
    assert score_batch(tmp_path, good).groundedness > score_batch(tmp_path, busywork).groundedness


def test_score_status_next_reads_the_generated_queue(tmp_path):
    _repo_with_files(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "STATUS.md").write_text(
        "## Next\n\n"
        "1. Harden a. Evidence: src/a.py:1; Acceptance: passes.\n"
        "2. Cover c. Evidence: tests/test_c.py:1; Acceptance: passes.\n"
    )
    score = score_status_next(tmp_path)
    assert score.size == 2
    assert score.grounded == 2  # both anchors resolve to real files
    assert score.bounded is True
