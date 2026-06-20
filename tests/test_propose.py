"""Task proposal from concrete repo signals."""

from __future__ import annotations

import shutil

from looptight.discovery import (
    Candidate,
    from_lint,
    from_skipped_tests,
    from_status_next,
    from_todos,
)
from looptight.propose import propose
from looptight.ranking import rank


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- extractors ------------------------------------------------------------

def test_from_todos_finds_markers_with_location(tmp_path):
    _write(tmp_path, "src/pkg/a.py", "x = 1  # TODO: pin the timeout\n# FIXME broken on win\n")
    cands = from_todos(tmp_path)
    titles = [c.title for c in cands]
    assert any("pin the timeout" in t for t in titles)
    assert any("broken on win" in t for t in titles)
    assert all(c.location and ":" in c.location for c in cands)


def test_from_todos_ignores_non_python(tmp_path):
    _write(tmp_path, "notes.txt", "TODO: not code\n")
    assert from_todos(tmp_path) == []


def test_from_todos_ignores_todo_inside_string_literal(tmp_path):
    # tokenize only yields COMMENT tokens, so a "# TODO:" inside a string
    # is never a false positive — this tests the key benefit of using tokenize.
    _write(tmp_path, "src/pkg/a.py", 'x = "# TODO: not a real comment"\n')
    assert from_todos(tmp_path) == []


def test_from_skipped_tests_detects_markers(tmp_path):
    _write(
        tmp_path,
        "tests/test_x.py",
        "import pytest\n@pytest.mark.skip(reason='flaky')\ndef test_a():\n    pass\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert len(cands) == 1
    assert "test_x.py" in cands[0].location


def test_from_skipped_tests_ignores_env_optin_gate(tmp_path):
    # An opt-in eval gated on an env var being set is intentional infrastructure,
    # not rot — even when the condition wraps onto a following line.
    _write(
        tmp_path,
        "tests/e2e_test.py",
        "import os\nimport pytest\n\n"
        "pytestmark = pytest.mark.skipif(\n"
        '    not os.environ.get("LOOPTIGHT_E2E"),\n'
        '    reason="real-agent eval; set LOOPTIGHT_E2E=1 to run",\n'
        ")\n\n\ndef test_e2e():\n    pass\n",
    )
    assert from_skipped_tests(tmp_path) == []


def test_from_skipped_tests_ignores_inner_skip_in_optin_module(tmp_path):
    # A module wholesale gated by an env-var pytestmark is opt-in infrastructure;
    # an imperative `pytest.skip(...)` guard inside it is not rot either.
    _write(
        tmp_path,
        "tests/e2e_test.py",
        "import os\nimport pytest\n\n"
        'pytestmark = pytest.mark.skipif(\n    not os.environ.get("E2E"), reason="opt-in"\n)\n\n\n'
        'def test_e2e():\n    if True:\n        pytest.skip("no agent on PATH")\n',
    )
    assert from_skipped_tests(tmp_path) == []


def test_from_skipped_tests_keeps_non_env_skipif(tmp_path):
    # A skipif on a real (non-env) condition is still a fix-me candidate.
    _write(
        tmp_path,
        "tests/test_y.py",
        "import sys\nimport pytest\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="broken on win")\n'
        "def test_b():\n    pass\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert len(cands) == 1


def test_from_skipped_tests_ignores_capability_guarded_skip(tmp_path):
    # An imperative `pytest.skip()` reached only when a required tool is absent
    # is an intentional capability guard — the test runs whenever the tool is
    # present (the normal CI case) — so it is not a bit-rotting skip to fix.
    _write(
        tmp_path,
        "tests/test_z.py",
        "import shutil\nimport pytest\n\n"
        "def test_needs_tool():\n"
        "    if shutil.which('ruff') is None:\n"
        "        pytest.skip('ruff not available')\n"
        "    assert True\n",
    )
    assert from_skipped_tests(tmp_path) == []


def test_from_skipped_tests_keeps_unconditional_inline_skip(tmp_path):
    # A bare `pytest.skip()` not guarded by any condition disables the test
    # outright — that is genuine rot, still a fix-me candidate.
    _write(
        tmp_path,
        "tests/test_w.py",
        "import pytest\n\n"
        "def test_disabled():\n"
        "    pytest.skip('disabled for now')\n"
        "    assert True\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert len(cands) == 1


def test_from_status_next_parses_numbered_list(tmp_path):
    _write(
        tmp_path,
        "docs/STATUS.md",
        "# Status\n\n## Next\n\n1. First thing to do. Acceptance: first passes.\n"
        "2. Second thing. Acceptance: second passes.\n\n## Other\n\n3. not this\n",
    )
    titles = [c.title for c in from_status_next(tmp_path)]
    assert titles == ["First thing to do", "Second thing"]


def test_from_status_next_absent_file_is_empty(tmp_path):
    assert from_status_next(tmp_path) == []


def test_from_status_next_joins_wrapped_continuation_lines(tmp_path):
    _write(
        tmp_path,
        "docs/STATUS.md",
        "## Next\n\n1. First line of the task\n"
        "   wraps onto a second line. Acceptance: first passes.\n"
        "2. Second task. Acceptance: second passes.\n",
    )

    titles = [c.title for c in from_status_next(tmp_path)]

    assert titles == [
        "First line of the task wraps onto a second line",
        "Second task",
    ]


def test_from_status_next_ignores_struck_through_resolved_items(tmp_path):
    _write(
        tmp_path,
        "docs/STATUS.md",
        "## Next\n\n1. ~~Resolved task.~~ Done.\n"
        "2. Still actionable. Acceptance: it passes.\n",
    )

    titles = [c.title for c in from_status_next(tmp_path)]

    assert titles == ["Still actionable"]


def test_from_status_next_rejects_task_without_acceptance(tmp_path):
    _write(tmp_path, "docs/STATUS.md", "## Next\n\n1. Vague task without a gate\n")

    assert from_status_next(tmp_path) == []


def test_from_status_next_returns_only_first_six_executable_tasks(tmp_path):
    tasks = "".join(
        f"{number}. Task {number}. Acceptance: task {number} passes.\n"
        for number in range(1, 9)
    )
    _write(tmp_path, "docs/STATUS.md", f"## Next\n\n{tasks}")

    candidates = from_status_next(tmp_path)

    assert [candidate.title for candidate in candidates] == [
        f"Task {number}" for number in range(1, 7)
    ]


def test_from_lint_finds_ruff_violations(tmp_path):
    if shutil.which("ruff") is None:
        import pytest
        pytest.skip("ruff not available")
    # F841: local variable assigned but never used — a real, simple ruff rule.
    _write(tmp_path, "src/pkg/bad.py", "def f():\n    x = 1\n    return 2\n")
    cands = from_lint(tmp_path)
    assert len(cands) >= 1
    assert all(c.source == "lint" for c in cands)
    assert any("F841" in c.title for c in cands)


def test_from_lint_empty_when_no_violations(tmp_path):
    _write(tmp_path, "src/pkg/ok.py", "def f():\n    return 1\n")
    cands = from_lint(tmp_path)
    assert cands == []


def test_from_lint_does_not_invoke_package_manager_when_ruff_is_absent(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "looptight.discovery.shutil.which",
        lambda command: "/usr/bin/uv" if command == "uv" else None,
    )

    def unexpected_subprocess(*args, **kwargs):
        raise AssertionError("lint discovery must not install or invoke tools")

    monkeypatch.setattr("looptight.discovery.subprocess.run", unexpected_subprocess)

    assert from_lint(tmp_path) == []


def test_from_lint_disables_ruff_cache(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr("looptight.discovery.shutil.which", lambda command: "/bin/ruff")

    def run(command, **kwargs):
        commands.append(command)
        return type("Result", (), {"stdout": ""})()

    monkeypatch.setattr("looptight.discovery.subprocess.run", run)

    assert from_lint(tmp_path) == []
    assert commands == [
        ["/bin/ruff", "check", "--no-cache", "--output-format", "concise", "--quiet"]
    ]


# --- dedup + rank ----------------------------------------------------------

def test_rank_orders_by_source_priority():
    todo = Candidate(title="t", source="todo", location="a.py:1", suggested_verify=None, score=0, detail="")
    lint = Candidate(title="l", source="lint", location="b.py:2", suggested_verify=None, score=0, detail="")
    ranked = rank([todo, lint])
    assert [c.source for c in ranked] == ["lint", "todo"]  # lint outranks todo


def test_propose_dedups_by_location_and_title(tmp_path):
    _write(tmp_path, "src/a.py", "# TODO: same thing\n")
    _write(tmp_path, "docs/STATUS.md", "## Next\n\n1. same thing\n")
    # Force a collision: a TODO and a STATUS item with the same normalized title
    # at different locations stay distinct; identical (loc, title) collapse.
    cands = propose(tmp_path)
    keys = {(c.location, c.title.lower()) for c in cands}
    assert len(keys) == len(cands)  # no exact duplicates


def test_propose_respects_limit(tmp_path):
    body = "".join(f"# TODO: task {i}\n" for i in range(20))
    _write(tmp_path, "src/a.py", body)
    assert len(propose(tmp_path, limit=5)) == 5
