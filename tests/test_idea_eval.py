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
    _area,
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


def test_evidence_refs_tolerates_markdown_emphasis_around_marker():
    # A bold/italic Evidence marker (``**Evidence:**``) must not capture the
    # emphasis markers as the anchor — the path follows them. Previously this
    # returned ['**'], which never resolves, so the real task was dropped.
    bold = _candidate("t", "Do it. **Evidence:** `src/a.py:10` Acceptance: x")
    assert evidence_refs(bold) == ["src/a.py:10"]
    italic = _candidate("t", "Do it. *Evidence:* src/b.py Acceptance: x")
    assert evidence_refs(italic) == ["src/b.py"]


def test_evidence_refs_strips_markdown_backticks():
    # The anchor is the bare path; markdown code-span backticks (the idiomatic
    # way paths are written, including in this repo's STATUS.md) are not part of
    # it, so every consumer — the resolver and the diversity metric — sees a
    # clean path.
    cand = _candidate("t", "Do it. Evidence: `src/a.py:10` Acceptance: x")
    assert evidence_refs(cand) == ["src/a.py:10"]


def test_grounding_accepts_backtick_delimited_path_with_spaces(tmp_path):
    # A backtick-delimited anchor delimits the path unambiguously, so a space inside
    # it is part of the path (`my src/a file.py:1`). A real grounded task whose file
    # has a space in its path was silently dropped because the bare-token rule cut the
    # anchor at the first space. A fabricated space-path still fails to resolve.
    (tmp_path / "my src").mkdir()
    (tmp_path / "my src" / "a file.py").write_text("x = 1\n")
    real = _candidate("Spaced", "Spaced. Evidence: `my src/a file.py:1` Acceptance: x")
    ghost = _candidate("Ghost", "Ghost. Evidence: `my src/ghost file.py:1` Acceptance: x")
    assert evidence_refs(real) == ["my src/a file.py:1"]
    assert is_grounded(tmp_path, real) is True
    assert is_grounded(tmp_path, ghost) is False  # a space-path still must resolve
    # A bare (un-delimited) anchor still ends at the first space, as before.
    bare = _candidate("Bare", "Bare. Evidence: src/a.py:10 trailing prose Acceptance: x")
    assert evidence_refs(bare) == ["src/a.py:10"]


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


def test_area_no_colon_ref_and_top_level_file_branches():
    # ref without a colon -> uses refs[0] directly; parent of "src/a.py" is "src"
    no_colon = _candidate("T", "T. Evidence: src/a.py; Acceptance: x")
    assert _area(no_colon) == "src"

    # top-level file -> parent is "."; fallback returns path_text itself
    top_level = _candidate("T2", "T2. Evidence: README.md; Acceptance: x")
    assert _area(top_level) == "README.md"


def test_area_with_colon_ref_strips_to_parent_dir():
    # idea_eval.py:51: the `if ":" in refs[0]` branch strips the position suffix
    # with rsplit(":", 1)[0]; a ref like "src/a.py:10" should yield area "src".
    with_line = _candidate("T", "T. Evidence: src/a.py:10; Acceptance: x")
    assert _area(with_line) == "src"


def test_area_returns_source_when_candidate_has_no_refs():
    # The fallback branch (idea_eval.py:54): when a candidate's detail names no
    # Evidence: anchor, _area returns candidate.source (the task source label).
    no_anchor = _candidate("Refactor everything", "Refactor everything. Acceptance: x")
    assert _area(no_anchor) == no_anchor.source


def test_evidence_refs_ignores_evidence_in_backtick_code_span():
    # Regression: `Evidence:` inside a backtick code span (e.g. "names no `Evidence:`
    # anchor") was matched by the regex, and the text up to the next backtick was
    # captured as a false anchor.  The negative lookbehind (?<!`) guards against this.
    cand = _candidate(
        "T",
        "T. The function names no `Evidence:` anchor here, but another `token`."
        " Evidence: src/a.py:1; Acceptance: x",
    )
    assert evidence_refs(cand) == ["src/a.py:1"]


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


def test_score_status_next_flags_an_over_budget_section_as_unbounded(tmp_path):
    # The eval's headline guard: a ## Next that exceeds the 1-6 bound must report
    # bounded=False. Previously from_status_next truncated at 6 before scoring, so
    # size was always <= 6 and bounded was always True — the upper bound was dead
    # code, and the misleading value reached propose --eval-batch --json.
    _repo_with_files(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    lines = ["## Next", ""]
    for i in range(8):
        lines.append(f"{i + 1}. Task {i}. Evidence: src/a.py:1; Acceptance: passes.")
    (docs / "STATUS.md").write_text("\n".join(lines) + "\n")
    score = score_status_next(tmp_path)
    assert score.size == 8  # the true count, not the truncated-to-6 count
    assert score.bounded is False


def test_score_status_next_counts_ungrounded_items_so_groundedness_is_honest(tmp_path):
    # The feedback signal must reflect the RAW batch the host wrote, not a grounding-filtered
    # subset. Pre-filtering ungrounded items here would force grounded==size (groundedness a
    # useless 1.0) and hide over-generation. 8 items, 3 with fabricated evidence.
    from looptight.discovery import from_status_next

    _repo_with_files(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    lines = ["## Next", ""]
    for i in range(5):
        lines.append(f"{i + 1}. Real task {i}. Evidence: src/a.py:1; Acceptance: passes.")
    for i in range(5, 8):
        lines.append(f"{i + 1}. Fabricated {i}. Evidence: src/ghost{i}.py:1; Acceptance: passes.")
    (docs / "STATUS.md").write_text("\n".join(lines) + "\n")

    score = score_status_next(tmp_path)
    assert score.size == 8  # all eight counted, not just the five grounded
    assert score.grounded == 5  # only the resolving anchors
    assert score.bounded is False  # the host over-generated past the 1-6 bound
    assert 0.0 < score.groundedness < 1.0  # an honest fraction, not a constant 1.0

    # The next/propose CLAIM path still drops the fabricated items (default enforcement).
    claimable = from_status_next(tmp_path, cap=None)
    assert len(claimable) == 5


def test_grounding_tolerates_a_trailing_sentence_period(tmp_path):
    # Evidence written as a sentence ("... Evidence: src/a.py.") must still resolve,
    # while a fabricated path with a period stays rejected.
    from looptight.grounding import is_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert is_grounded(tmp_path, "Do it. Evidence: src/a.py.") is True
    assert is_grounded(tmp_path, "Do it. Evidence: src/ghost.py.") is False


def test_grounding_tolerates_markdown_backticked_evidence(tmp_path):
    # Evidence paths are idiomatically wrapped in markdown backticks
    # (``Evidence: `src/a.py:10` ``) — that is how this repo's own STATUS.md and
    # an LLM-generated task write them. The grounding gate must resolve the path
    # inside the backticks, or it silently drops a real, grounded task and the
    # loop stalls on a false no_work.
    from looptight.grounding import evidence_is_truthful, is_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert is_grounded(tmp_path, "Do it. Evidence: `src/a.py:10` Acceptance: ok") is True
    assert evidence_is_truthful(tmp_path, "Do it. Evidence: `src/a.py`") is True
    # A backtick-wrapped fabricated path still fails.
    assert is_grounded(tmp_path, "Do it. Evidence: `src/ghost.py`") is False


def test_strip_anchor_decoration_normalizes_idiomatic_decoration():
    # The shared normalizer used by the gate and the swarm planner: strip a
    # markdown code span and a trailing period; keep the position and a leading
    # dot. Locking it here means the tolerance is defined in one tested place.
    from looptight.grounding import strip_anchor_decoration

    assert strip_anchor_decoration("`src/a.py:10`") == "src/a.py:10"  # position kept
    assert strip_anchor_decoration("src/a.py.") == "src/a.py"         # trailing period
    assert strip_anchor_decoration("`src/a.py`.") == "src/a.py"       # backtick then period
    assert strip_anchor_decoration("./src/a.py") == "./src/a.py"      # leading dot kept
    assert strip_anchor_decoration(".looptight.toml") == ".looptight.toml"


def test_ref_resolves_keeps_meaningful_leading_dots(tmp_path):
    # Stripping a markdown code span must not eat a meaningful leading dot: a
    # `./path` relative prefix and a `.dotfile` are valid anchors. (Regression:
    # an over-broad strip of leading periods rejected both.)
    from looptight.grounding import ref_resolves

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / ".looptight.toml").write_text("v", encoding="utf-8")
    assert ref_resolves(tmp_path, "./src/a.py") is True
    assert ref_resolves(tmp_path, "./src/a.py:10") is True
    assert ref_resolves(tmp_path, ".looptight.toml") is True
    assert ref_resolves(tmp_path, "`.looptight.toml`") is True  # backticked dotfile


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


def test_ref_resolves_strips_trailing_period(tmp_path):
    # ref_resolves strips a trailing '.' so evidence refs that end a sentence
    # (e.g. "Evidence: src/x.py.") resolve correctly.
    from looptight.grounding import ref_resolves

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("x", encoding="utf-8")
    assert ref_resolves(tmp_path, "src/x.py.") is True   # trailing period stripped
    assert ref_resolves(tmp_path, "src/x.py") is True    # no period: still works
    assert ref_resolves(tmp_path, "src/missing.py.") is False  # stripped but absent


def test_strip_position_suffix_multi_level_and_range():
    from looptight.grounding import strip_position_suffix

    assert strip_position_suffix("src/a.py:10:5") == "src/a.py"
    assert strip_position_suffix("src/a.py:10-20") == "src/a.py"


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


def test_ref_resolves_handles_line_and_column_suffix(tmp_path):
    # Evidence may be path, path:line, or path:line:col (e.g. a lint location).
    # All three must resolve to the real file — stripping only one suffix wrongly
    # drops path:line:col.
    from looptight.grounding import ref_resolves

    (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
    assert ref_resolves(tmp_path, "real.py") is True
    assert ref_resolves(tmp_path, "real.py:1") is True
    assert ref_resolves(tmp_path, "real.py:1:5") is True  # path:line:col


def test_ref_resolves_handles_line_range_suffix(tmp_path):
    # Evidence anchors idiomatically cite a line *range* (`path:120-145`). The gate
    # is the loop's single point of failure, so a real file cited with a range must
    # resolve, not be dropped as fabricated evidence.
    from looptight.grounding import evidence_is_truthful, ref_resolves

    (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
    assert ref_resolves(tmp_path, "real.py:120-145") is True  # line range
    assert ref_resolves(tmp_path, "real.py:5-10:2") is True  # range then col
    assert ref_resolves(tmp_path, "real.py:1") is True  # plain line still resolves
    assert ref_resolves(tmp_path, "missing.py:1-5") is False  # range, absent file
    # The gate accepts a task citing a real file with an idiomatic line range.
    assert evidence_is_truthful(tmp_path, "Do x. Evidence: real.py:40-60") is True
