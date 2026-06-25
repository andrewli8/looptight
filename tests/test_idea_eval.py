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


def test_grounding_tolerates_a_trailing_sentence_period(tmp_path):
    # Evidence written as a sentence ("... Evidence: src/a.py.") must still resolve,
    # while a fabricated path with a period stays rejected.
    from looptight.grounding import is_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert is_grounded(tmp_path, "Do it. Evidence: src/a.py.") is True
    assert is_grounded(tmp_path, "Do it. Evidence: src/ghost.py.") is False


def test_ref_resolves_boundary_cases(tmp_path):
    # Direct coverage of ref_resolves edge cases not reached through is_grounded.
    from looptight.grounding import ref_resolves

    (tmp_path / "real.py").write_text("x", encoding="utf-8")
    assert ref_resolves(tmp_path, "real.py") is True           # plain path, no line
    assert ref_resolves(tmp_path, "real.py:42") is True        # path with line number
    assert ref_resolves(tmp_path, ":5") is False               # colon-only, empty path
    assert ref_resolves(tmp_path, "") is False                 # empty string
    assert ref_resolves(tmp_path, "/etc/passwd") is False      # absolute path
    assert ref_resolves(tmp_path, "../sibling.py") is False    # path traversal


def test_evidence_is_truthful_is_the_lenient_gate(tmp_path):
    # The gate discovery uses: every named anchor must resolve, but an item naming no
    # anchor is allowed (so hand-written lists work), unlike strict is_grounded.
    from looptight.grounding import evidence_is_truthful, is_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert evidence_is_truthful(tmp_path, "no anchor here") is True  # vacuously true
    assert is_grounded(tmp_path, "no anchor here") is False  # strict needs an anchor
    assert evidence_is_truthful(tmp_path, "Evidence: src/a.py:1") is True
    assert evidence_is_truthful(tmp_path, "Evidence: src/ghost.py:1") is False


def test_batch_score_as_dict_pins_all_fields():
    # as_dict() is used in protocol_commands.py:133 for JSON output; pin all 6 fields.
    from looptight.idea_eval import BatchScore
    score = BatchScore(size=3, grounded=2, flexibility=2, distinct=3, bounded=True)
    d = score.as_dict()
    assert d == {
        "size": 3,
        "grounded": 2,
        "groundedness": round(2 / 3, 3),
        "flexibility": 2,
        "distinct": 3,
        "bounded": True,
    }
