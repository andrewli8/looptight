from looptight.discovery import Candidate
from looptight.idea_identity import idea_id


def _c(source, location, title):
    return Candidate(title=title, source=source, location=location,
                     suggested_verify=None, score=0.0, detail="d", acceptance="a")


def test_lint_identity_ignores_line_and_message():
    a = _c("lint", "src/looptight/foo.py:10", "fix E501: line too long")
    b = _c("lint", "src/looptight/foo.py:42", "fix E501: line too long (88 > 79)")
    assert idea_id(a) == idea_id(b)  # same file + rule => same idea


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
