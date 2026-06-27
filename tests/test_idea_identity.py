from looptight.discovery import Candidate
from looptight.idea_identity import idea_id


def _c(source, location, title):
    return Candidate(title=title, source=source, location=location,
                     suggested_verify=None, score=0.0, detail="d", acceptance="a")


def test_lint_identity_ignores_line_and_message():
    a = _c("lint", "src/looptight/foo.py:10", "fix E501: line too long")
    b = _c("lint", "src/looptight/foo.py:42", "fix E501: line too long (88 > 79)")
    assert idea_id(a) == idea_id(b)  # same file + rule => same idea


def test_lint_identity_is_line_stable_for_real_path_line_col_locations():
    # from_lint emits `path:line:col` locations. The identity must stay stable
    # when a finding shifts lines (e.g. an import added above it), or the
    # self-model and cooldown miss a re-proposed lint idea after any edit. The
    # other lint tests use single-segment `path:line` and so never caught this.
    a = _c("lint", "src/foo.py:1:8", "fix F401: os imported but unused")
    b = _c("lint", "src/foo.py:5:8", "fix F401: os imported but unused")
    assert idea_id(a) == idea_id(b)


def test_lint_identity_differs_by_rule():
    a = _c("lint", "src/looptight/foo.py:10", "fix E501: line too long")
    b = _c("lint", "src/looptight/foo.py:10", "fix F401: unused import")
    assert idea_id(a) != idea_id(b)


def test_todo_identity_ignores_line_keeps_text():
    a = _c("todo", "src/looptight/foo.py:10", "handle the empty case")
    b = _c("todo", "src/looptight/foo.py:99", "handle the empty case")
    assert idea_id(a) == idea_id(b)


def test_status_next_identity_uses_normalized_title():
    a = _c("status-next", "docs/STATUS.md:12", "Cover  the  retry path")
    b = _c("task-file", "docs/STATUS.md:5", "cover the retry path")
    # title normalization matches; source class (curated) is shared
    assert idea_id(a) == idea_id(b)


def test_identity_is_twelve_char_hex():
    v = idea_id(_c("lint", "src/looptight/foo.py:10", "fix E501: x"))
    assert len(v) == 12 and all(ch in "0123456789abcdef" for ch in v)


def test_lint_fallback_without_rule_code_is_line_stable():
    a = _c("lint", "src/foo.py:10", "remove trailing whitespace")
    b = _c("lint", "src/foo.py:42", "remove trailing whitespace")
    assert idea_id(a) == idea_id(b)


def test_skipped_test_identity_ignores_location():
    a = _c("skipped-test", "tests/test_a.py:10", "test_retry_path")
    b = _c("skipped-test", "tests/test_b.py:99", "test_retry_path")
    assert idea_id(a) == idea_id(b)


def test_idea_id_with_none_location_returns_nonempty_hex():
    # _path(None) returns "" (idea_identity.py:31); idea_id must still return a
    # valid 12-char hex string rather than raising or returning an empty string.
    c = _c("todo", None, "handle the empty case")
    result = idea_id(c)
    assert len(result) == 12 and all(ch in "0123456789abcdef" for ch in result)


def test_idea_id_generic_source_is_stable_and_distinct():
    # An unknown source (e.g. "verify") falls through to the generic tuple
    # (idea_identity.py:49). The identity must be stable across calls and differ
    # from a known-source candidate with the same title.
    a = _c("verify", "src/foo.py:1", "check output")
    b = _c("verify", "src/foo.py:1", "check output")
    assert idea_id(a) == idea_id(b)  # stable
    known = _c("todo", "src/foo.py:1", "check output")
    assert idea_id(a) != idea_id(known)  # distinct from a known-source candidate
