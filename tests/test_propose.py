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
from looptight.experience import Model
from looptight.idea_identity import idea_id
from looptight.propose import _apply_cooldown, propose
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


def test_from_todos_finds_js_markers_outside_src_layout(tmp_path):
    # The common React/Next/Vue layout puts source under app/components/lib, not
    # src/. JS TODO discovery must be layout-agnostic (like the Python path), or a
    # whole project's markers are silently missed; vendored dirs stay pruned.
    _write(tmp_path, "components/Button.tsx", "// TODO: real component todo\nexport const B = 1;\n")
    _write(tmp_path, "lib/util.mjs", "// FIXME: lib util\n")
    _write(tmp_path, "node_modules/dep/index.js", "// TODO: vendored, must be pruned\n")
    titles = [c.title for c in from_todos(tmp_path)]
    assert "real component todo" in titles
    assert "lib util" in titles
    assert "vendored, must be pruned" not in titles


def test_from_todos_ignores_non_python(tmp_path):
    _write(tmp_path, "notes.txt", "TODO: not code\n")
    assert from_todos(tmp_path) == []


def test_from_todos_ignores_todo_inside_string_literal(tmp_path):
    # tokenize only yields COMMENT tokens, so a "# TODO:" inside a string
    # is never a false positive — this tests the key benefit of using tokenize.
    _write(tmp_path, "src/pkg/a.py", 'x = "# TODO: not a real comment"\n')
    assert from_todos(tmp_path) == []


def test_from_todos_skips_malformed_python_file(tmp_path):
    # _comments() catches tokenize.TokenError/SyntaxError/OSError/UnicodeDecodeError
    # and returns silently; a file with a lone \x00 byte triggers that path.
    path = tmp_path / "src" / "pkg" / "bad.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")
    assert from_todos(tmp_path) == []


def test_from_skipped_tests_ignores_py_marker_in_multiline_string(tmp_path):
    # A pytest.skip(...) on a line inside a triple-quoted multi-line string is
    # example text, not a real skip, and must not be surfaced; a real top-level
    # pytest.skip(...) still is.
    _write(
        tmp_path,
        "tests/test_a.py",
        "def test_doc():\n"
        '    doc = """\n'
        '    pytest.skip("example inside a docstring, not real")\n'
        '    """\n'
        "    assert doc\n\n"
        "def test_real():\n"
        '    pytest.skip("genuinely disabled")\n'
        "    assert True\n",
    )
    cands = from_skipped_tests(tmp_path)
    locs = [c.location for c in cands]
    assert any(loc.endswith(":8") for loc in locs)  # the real top-level skip
    assert not any(loc.endswith(":3") for loc in locs)  # the one inside the string
    assert len(cands) == 1


def test_from_skipped_tests_ignores_js_marker_in_multiline_template_literal(tmp_path):
    # An it.skip(...) on a continuation line of a multi-line backtick template
    # literal (e.g. example code embedded in a string) is not a real skipped test
    # and must not be surfaced; a real it.skip(...) outside the literal still is.
    _write(
        tmp_path,
        "tests/a.test.js",
        "const example = `\n"
        'it.skip("documentation, not a real skip", () => {});\n'
        "`;\n"
        'it.skip("real skipped test", () => {});\n',
    )
    cands = from_skipped_tests(tmp_path)
    names = [c.title for c in cands]
    assert any("real skipped test" in n for n in names)
    assert not any("documentation, not a real skip" in n for n in names)
    assert len(cands) == 1


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


def test_from_skipped_tests_keeps_skip_whose_reason_mentions_environ(tmp_path):
    # The env-gate filter must read code, not the *reason* string: a skip whose
    # message merely mentions "os.environ" is still rot to fix, not an opt-in gate.
    _write(
        tmp_path,
        "tests/test_r.py",
        "import pytest\n\n"
        '@pytest.mark.skip(reason="os.environ setup is broken")\n'
        "def test_a():\n    pass\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert len(cands) == 1
    assert "test_r.py" in cands[0].location


def test_from_skipped_tests_keeps_unconditional_skip_with_environ_reason(tmp_path):
    # A bare top-level pytest.skip() whose reason mentions "environ" is genuine
    # rot, not an env gate — the reason string must not suppress it.
    _write(
        tmp_path,
        "tests/test_s.py",
        "import pytest\n\n"
        "def test_b():\n"
        '    pytest.skip("environ not configured")\n'
        "    assert True\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert len(cands) == 1


def test_from_skipped_tests_classifies_skip_by_enclosing_conditional(tmp_path):
    # A pytest.skip() inside an if/elif (even nested) is an intentional capability
    # guard, not rot; one under a for-loop (no if) is unconditional rot.
    _write(
        tmp_path,
        "tests/test_c.py",
        "import pytest, shutil\n\n"            # 1, 2
        "def test_guarded():\n"                # 3
        "    if True:\n"                       # 4
        "        if shutil.which('tool') is None:\n"  # 5
        "            pytest.skip('tool missing')\n"   # 6 (nested-if guard)
        "    assert True\n\n"                  # 7, 8
        "def test_looped():\n"                 # 9
        "    for _ in range(1):\n"             # 10
        "        pytest.skip('looped')\n",     # 11 (for-loop rot)
    )
    locs = [c.location for c in from_skipped_tests(tmp_path)]
    assert any(loc.endswith(":11") for loc in locs)       # for-loop skip is rot
    assert not any(loc.endswith(":6") for loc in locs)    # nested-if guard ignored


def test_from_task_file_rejects_paths_outside_the_repo(tmp_path):
    # A configured task_file must stay within the repo: an absolute path or a `..`
    # traversal is rejected even when the target exists with valid tasks.
    from looptight.discovery import from_task_file

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.md"  # a sibling of the repo, reachable via ../
    outside.write_text("## Next\n\n1. Leak. Acceptance: it passes.\n", encoding="utf-8")

    assert from_task_file(repo, str(outside)) == []     # absolute path rejected
    assert from_task_file(repo, "../outside.md") == []  # .. traversal rejected


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


def test_from_status_next_rejects_fabricated_evidence_but_keeps_real_and_unanchored(tmp_path):
    # The live grounding gate: a generated task that CLAIMS evidence which does not
    # resolve is dropped (the busywork trap), while a task with resolving evidence and
    # a legacy task that names no evidence both survive (backward compatible).
    _write(tmp_path, "src/real.py", "# real\n")
    _write(
        tmp_path,
        "docs/STATUS.md",
        "## Next\n\n"
        "1. Real task. Evidence: src/real.py:1; Acceptance: it passes.\n"
        "2. Busywork. Evidence: src/made_up.py:1; Acceptance: it passes.\n"
        "3. Legacy task. Acceptance: it passes.\n",
    )

    titles = [c.title for c in from_status_next(tmp_path)]
    assert len(titles) == 2  # the fabricated-evidence item is dropped
    assert any(t.startswith("Real task") for t in titles)  # resolving evidence survives
    assert "Legacy task" in titles  # unanchored legacy item survives
    assert not any("Busywork" in t for t in titles)


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


def test_from_lint_dedups_to_one_task_per_file_and_rule(tmp_path):
    if shutil.which("ruff") is None:
        import pytest
        pytest.skip("ruff not available")
    # Two F401 (unused import) in one file collapse to a single task; a third in
    # another file stays its own. One task per (file, rule). A regression removing
    # the dedup would surface duplicate lint tasks.
    _write(tmp_path, "a.py", "import os\nimport sys\n")  # two unused imports -> two F401
    _write(tmp_path, "b.py", "import json\n")            # one unused import
    f401 = [c for c in from_lint(tmp_path) if "F401" in c.title]
    files = {c.location.split(":")[0] for c in f401}
    assert files == {"a.py", "b.py"}  # one entry per file
    assert sum(c.location.startswith("a.py") for c in f401) == 1  # a.py's two collapsed


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


def test_from_lint_returns_empty_on_oserror(tmp_path, monkeypatch):
    # If ruff cannot be launched (e.g. exec permission error), from_lint must
    # degrade gracefully rather than propagating the OSError to the caller.
    monkeypatch.setattr("looptight.discovery.shutil.which", lambda cmd: "/bin/ruff")
    monkeypatch.setattr(
        "looptight.discovery.subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("exec failed")),
    )
    assert from_lint(tmp_path) == []


def test_from_lint_returns_empty_on_timeout(tmp_path, monkeypatch):
    import subprocess as _subprocess
    # A hung ruff process (TimeoutExpired) must not propagate to the caller.
    monkeypatch.setattr("looptight.discovery.shutil.which", lambda cmd: "/bin/ruff")
    monkeypatch.setattr(
        "looptight.discovery.subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(
            _subprocess.TimeoutExpired(cmd="/bin/ruff", timeout=60)
        ),
    )
    assert from_lint(tmp_path) == []


# --- dedup + rank ----------------------------------------------------------

def test_rank_orders_by_source_priority():
    todo = Candidate(title="t", source="todo", location="a.py:1", suggested_verify=None, score=0, detail="")
    lint = Candidate(title="l", source="lint", location="b.py:2", suggested_verify=None, score=0, detail="")
    ranked = rank([todo, lint])
    assert [c.source for c in ranked] == ["lint", "todo"]  # lint outranks todo


def test_rank_configured_task_file_outranks_todo():
    todo = Candidate(title="t", source="todo", location="a.py:1", suggested_verify=None, score=0, detail="")
    task_file = Candidate(title="f", source="task-file", location="TASKS.md:1", suggested_verify=None, score=0, detail="")
    ranked = rank([todo, task_file])
    assert [c.source for c in ranked] == ["task-file", "todo"]  # configured file outranks ad-hoc todo


def test_rank_human_curated_sources_outrank_automated_lint():
    # Human/planner-curated intent (task-file, status-next) should run before an
    # automated lint nit; task-file stays above status-next.
    lint = Candidate(title="l", source="lint", location="b.py:2", suggested_verify=None, score=0, detail="")
    status = Candidate(title="s", source="status-next", location="docs/STATUS.md:5", suggested_verify=None, score=0, detail="")
    task_file = Candidate(title="f", source="task-file", location="TASKS.md:1", suggested_verify=None, score=0, detail="")
    ranked = rank([lint, status, task_file])
    assert [c.source for c in ranked] == ["task-file", "status-next", "lint"]


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


# --- cooldown suppression --------------------------------------------------


def _c(title):
    return Candidate(title=title, source="lint", location="src/a.py:1",
                     suggested_verify=None, score=60.0, detail="d", acceptance="a")


def test_apply_cooldown_filters_suppressed_ideas():
    keep = _c("fix E501: x")
    drop = _c("fix F401: y")
    model = Model(failed={idea_id(drop): 2})
    out = _apply_cooldown([keep, drop], model, max_failures=2)
    assert out == [keep]


def test_apply_cooldown_noop_without_model():
    cands = [_c("fix E501: x")]
    assert _apply_cooldown(cands, Model(), max_failures=2) == cands


# --- rank_with_model -----------------------------------------------------------

from looptight.ranking import rank_with_model  # noqa: E402


def _rc(source, title):
    return Candidate(title=title, source=source, location="x:1",
                     suggested_verify=None, score=0.0, detail="d", acceptance="a")


def test_rank_with_empty_model_matches_plain_rank():
    cs = [_rc("lint", "a"), _rc("task-file", "b"), _rc("todo", "c")]
    assert [c.title for c in rank_with_model(cs, Model())] == [c.title for c in rank(cs)]


def test_reweight_never_inverts_curated_over_automated():
    cs = [_rc("task-file", "curated"), _rc("lint", "auto")]
    # lint lands a lot, task-file has no data: lint is boosted but must stay below curated
    model = Model(category_landed={"lint": 100}, category_failed={"lint": 0})
    ordered = [c.source for c in rank_with_model(cs, model)]
    assert ordered[0] == "task-file"


def test_max_boosted_automated_stays_below_lowest_curated_tier():
    # The tightest case of the curated-over-automated invariant: status-next is
    # the lowest-weight curated source and lint the highest automated. With lint
    # maximally boosted it must still rank below status-next (a ~0.2 margin). A
    # small bump to _REWEIGHT_HI or a weight would silently invert this; the
    # other tests use task-file, which has far more margin, so they miss it.
    cs = [_rc("status-next", "planned"), _rc("lint", "nit")]
    model = Model(category_landed={"lint": 1000}, category_failed={"lint": 0})
    ordered = [c.source for c in rank_with_model(cs, model)]
    assert ordered == ["status-next", "lint"]


def test_failed_curated_source_stays_above_automated():
    cs = [_rc("task-file", "human task"), _rc("status-next", "planned"), _rc("lint", "nit")]
    # task-file AND status-next each have a recorded failure; lint has none
    model = Model(category_failed={"task-file": 3, "status-next": 2})
    ordered = [c.source for c in rank_with_model(cs, model)]
    assert ordered.index("task-file") < ordered.index("lint")
    assert ordered.index("status-next") < ordered.index("lint")


# --- dedupe -------------------------------------------------------------------

from looptight.ranking import dedupe  # noqa: E402


def _dc(title, location):
    return Candidate(title=title, source="lint", location=location,
                     suggested_verify=None, score=0.0, detail="d")


def test_dedupe_collapses_whitespace_and_case():
    # Same location + title differing only by case/whitespace → duplicate dropped.
    first = _dc("Fix  Widget", "src/x.py:1")
    dup = _dc("fix widget", "src/x.py:1")
    other = _dc("Fix Other", "src/y.py:2")
    result = dedupe([first, dup, other])
    assert len(result) == 2
    assert result[0].title == "Fix  Widget"  # first occurrence kept
    assert result[1].title == "Fix Other"    # distinct location kept


def test_dedupe_treats_none_location_as_key():
    # Two candidates with location=None and the same normalized title → deduplicated.
    c1 = _dc("Task A", None)
    c2 = _dc("task a", None)
    c3 = _dc("Task B", None)
    result = dedupe([c1, c2, c3])
    assert len(result) == 2


def test_dedupe_empty_list_returns_empty():
    assert dedupe([]) == []


# --- polyglot TODO discovery (JS/TS), grounded by the adoption review ---

def test_from_todos_finds_typescript_and_python_in_one_repo(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("const x = 1; // TODO: wire up retries\n")
    (tmp_path / "src" / "b.py").write_text("# TODO: handle empty case\n")
    locs = {c.location for c in from_todos(tmp_path)}
    assert "src/a.ts:1" in locs
    assert "src/b.py:1" in locs
    assert all(c.source == "todo" for c in from_todos(tmp_path))


def test_from_todos_reads_jsx_tsx_and_block_comments(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "c.tsx").write_text("export const C = () => null; /* FIXME: a11y */\n")
    (tmp_path / "src" / "d.jsx").write_text("// TODO: memoize\nconst d = 1;\n")
    locs = {c.location for c in from_todos(tmp_path)}
    assert "src/c.tsx:1" in locs
    assert "src/d.jsx:1" in locs


def test_from_todos_ignores_js_marker_inside_string_literal(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src").mkdir()
    # The marker is inside a string, not a comment: must not be a hit.
    (tmp_path / "src" / "a.ts").write_text('const s = "// TODO not real";\n')
    assert from_todos(tmp_path) == []


# --- polyglot skipped-test discovery (JS/TS) ---

def test_from_skipped_tests_finds_js_ts_skips(tmp_path):
    from looptight.discovery import from_skipped_tests
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.test.ts").write_text('it.skip("does the thing", () => {});\n')
    (tmp_path / "tests" / "b.spec.js").write_text('xit("legacy case", () => {});\n')
    (tmp_path / "tests" / "c.test.tsx").write_text('describe.skip("a group", () => {});\n')
    cands = from_skipped_tests(tmp_path)
    locs = {c.location for c in cands}
    assert "tests/a.test.ts:1" in locs
    assert "tests/b.spec.js:1" in locs
    assert "tests/c.test.tsx:1" in locs
    assert all(c.source == "skipped-test" for c in cands)


def test_from_skipped_tests_finds_jest_xtest_alias(tmp_path):
    # `xtest(` is a documented Jest alias for `test.skip()`, like xit/xdescribe.
    from looptight.discovery import from_skipped_tests
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "legacy.test.js").write_text(
        'xtest("legacy case", () => {});\n', encoding="utf-8"
    )
    cands = from_skipped_tests(tmp_path)
    locs = {c.location for c in cands}
    assert "tests/legacy.test.js:1" in locs
    assert any("legacy case" in c.title for c in cands)


def test_from_skipped_tests_ignores_js_skip_in_string_or_comment(tmp_path):
    from looptight.discovery import from_skipped_tests
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.test.ts").write_text(
        'const s = "it.skip(should not count)";\n// it.skip in a comment\nit("real", () => {});\n'
    )
    assert from_skipped_tests(tmp_path) == []


# --- broaden JS/TS discovery to colocated test files (task-file Next #1) ---

def test_discovery_finds_colocated_and_root_js_tests(tmp_path):
    from looptight.discovery import from_skipped_tests, from_todos
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.test.ts").write_text('it.skip("x", () => {}); // TODO: fix later\n')
    (tmp_path / "__tests__").mkdir()
    (tmp_path / "__tests__" / "bar.spec.js").write_text('xit("y", () => {});\n')
    todo_locs = {c.location for c in from_todos(tmp_path)}
    skip_locs = {c.location for c in from_skipped_tests(tmp_path)}
    assert "src/foo.test.ts:1" in todo_locs
    assert "src/foo.test.ts:1" in skip_locs
    assert "__tests__/bar.spec.js:1" in skip_locs


def test_discovery_skips_node_modules(tmp_path):
    from looptight.discovery import from_skipped_tests
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "a.test.js").write_text('it.skip("x", () => {});\n')
    assert from_skipped_tests(tmp_path) == []


def test_from_todos_reads_multiline_block_comment(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("/*\n  TODO: refactor this\n*/\nconst x = 1;\n")
    locs = {c.location for c in from_todos(tmp_path)}
    assert "src/a.ts:2" in locs  # marker on a continuation line inside the block


def test_from_todos_block_comment_still_ignores_string_with_marker(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src").mkdir()
    # A `//` marker inside a string must still not count (single-line behavior).
    (tmp_path / "src" / "b.ts").write_text('const s = "// TODO nope";\n')
    assert from_todos(tmp_path) == []


def test_discovery_prunes_vendored_dirs_under_src(tmp_path):
    from looptight.discovery import from_todos
    (tmp_path / "src" / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "node_modules" / "pkg" / "a.ts").write_text("// TODO: vendored, ignore\n")
    (tmp_path / "src" / "real.ts").write_text("// TODO: keep me\n")
    locs = {c.location for c in from_todos(tmp_path)}
    assert "src/real.ts:1" in locs
    assert not any("node_modules" in loc for loc in locs)


def test_from_skipped_tests_ignores_skip_marker_in_trailing_comment(tmp_path):
    from looptight.discovery import from_skipped_tests
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.test.ts").write_text(
        "const x = 1; // it.skip(foo) handle later\n"
        "const y = 2; /* describe.skip(bar) */\n"
        'it.skip("real one", () => {});\n'
    )
    locs = {c.location for c in from_skipped_tests(tmp_path)}
    assert "tests/a.test.ts:3" in locs  # the real skip on a code line
    assert "tests/a.test.ts:1" not in locs  # marker inside a trailing // comment
    assert "tests/a.test.ts:2" not in locs  # marker inside a trailing /* */ comment


def test_js_line_comment_detects_comment_after_escaped_backslash():
    # An escaped backslash (\\) ends the string, so a following // comment is real.
    from looptight.discovery import _js_line_comment
    body, block_open, _t = _js_line_comment('let x = "\\\\" // TODO: fix')
    assert body is not None and "TODO: fix" in body
    assert block_open is False


def test_js_line_comment_no_comment_returns_none():
    # A plain code line with no comment token must return (None, False).
    from looptight.discovery import _js_line_comment
    body, block_open, _t = _js_line_comment("const x = 1;")
    assert body is None
    assert block_open is False


def test_js_line_comment_unclosed_block_comment_sets_block_open():
    # A /* that is never closed on this line must return block_open=True so the
    # caller continues reading the next lines as comment continuation.
    from looptight.discovery import _js_line_comment
    body, block_open, _t = _js_line_comment("/* TODO: unfinished")
    assert body is not None and "TODO: unfinished" in body
    assert block_open is True


def test_js_line_comment_inline_block_comment_stays_closed():
    # A /* ... */ fully closed on one line must not set block_open.
    from looptight.discovery import _js_line_comment
    body, block_open, _t = _js_line_comment("doThing(); /* TODO: inline */ more();")
    assert body is not None and "TODO: inline" in body
    assert block_open is False


def test_js_line_comment_ignores_slash_inside_backtick_template_literal():
    # A // inside a backtick template literal is not a real comment.
    from looptight.discovery import _js_line_comment
    body, block_open, _template = _js_line_comment("`url: http://example.com`")
    assert body is None
    assert block_open is False


def test_from_todos_ignores_marker_inside_multiline_template_literal(tmp_path):
    # A // TODO on a continuation line of a multi-line backtick template literal is
    # string content, not a comment, and must not be surfaced as a task; a real
    # // TODO after the template closes must still be found.
    from looptight.discovery import from_todos

    _write(
        tmp_path,
        "src/a.js",
        "const t = `\n"
        "// TODO: inside template literal, not real\n"
        "`;\n"
        "// TODO: real comment after template\n",
    )
    todos = from_todos(tmp_path)
    titles = [c.title for c in todos]
    assert "real comment after template" in titles
    assert "inside template literal, not real" not in titles
    assert len(todos) == 1


def test_js_line_comment_reports_open_template_literal(tmp_path):
    # An unclosed backtick at end of line means the next line begins inside the
    # template literal; the scanner reports this so the caller can track it.
    from looptight.discovery import _js_line_comment
    body, block_open, template_open = _js_line_comment("const t = `opening")
    assert body is None
    assert block_open is False
    assert template_open is True
    # Starting a line already inside a template, a // is string content.
    body2, _b, still_open = _js_line_comment("// not a comment", in_template=True)
    assert body2 is None
    assert still_open is True
    # The closing backtick ends the template; a real // after it is a comment.
    body3, _b3, closed = _js_line_comment("`; // real", in_template=True)
    assert body3 is not None and "real" in body3
    assert closed is False


def test_from_todos_is_layout_agnostic(tmp_path):
    # Discovery must find TODOs in flat packages (pkg/x.py) and top-level modules
    # (app.py), not only src/ and tests/ — the majority of Python projects.
    _write(tmp_path, "myapp/core.py", "x = 1  # TODO: handle the empty case\n")
    _write(tmp_path, "app.py", "y = 2  # FIXME: top-level module bug\n")
    locs = {c.location for c in from_todos(tmp_path)}
    assert any("myapp/core.py" in loc for loc in locs), "flat package TODO missed"
    assert any("app.py" in loc for loc in locs), "top-level module TODO missed"


def test_from_todos_prunes_vendored_and_build_dirs(tmp_path):
    # A TODO inside a virtualenv or build output must never be surfaced as work.
    _write(tmp_path, ".venv/lib/site.py", "# TODO: not my code\n")
    _write(tmp_path, "build/gen.py", "# TODO: generated\n")
    assert from_todos(tmp_path) == []


def test_from_skipped_tests_is_layout_agnostic(tmp_path):
    # Skipped tests in a singular `test/` dir (not `tests/`) must be found too.
    _write(
        tmp_path, "test/test_x.py",
        "import pytest\n@pytest.mark.skip(reason='flaky')\ndef test_a():\n    pass\n",
    )
    cands = from_skipped_tests(tmp_path)
    assert any("test/test_x.py" in c.location for c in cands), "singular test/ dir missed"


def test_task_files_enforce_truthful_evidence(tmp_path):
    # The anti-fabrication gate must apply to configured task-files too, not only
    # generated ## Next. A task claiming non-resolving evidence is ungrounded
    # busywork and is dropped; unanchored and resolving-evidence tasks are kept.
    from looptight.discovery import discover

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tasks.md").write_text(
        "## Next\n\n"
        "1. Harden real. Evidence: src/real.py:1; Acceptance: passes.\n"
        "2. Fix ghost. Evidence: src/ghost_nope.py:9; Acceptance: passes.\n"
        "3. A note with no anchor. Acceptance: passes.\n",
        encoding="utf-8",
    )
    titles = [c.title for c in discover(tmp_path, task_files=("tasks.md",))]
    assert any("Harden real" in t for t in titles)  # resolving evidence kept
    assert any("no anchor" in t for t in titles)  # unanchored item kept
    assert not any("ghost" in t for t in titles)  # fabricated evidence dropped


def test_from_todos_ignores_marker_prefixed_compound_words(tmp_path):
    # A marker must be followed by ':', whitespace, or end of line. Prose that
    # merely starts with a marker-prefixed compound word (fixme-style, todo-list,
    # hack-ish) is not a task and must not be surfaced.
    _write(
        tmp_path, "src/p.py",
        "a = 1  # fixme-style naming, not a marker\n"
        "b = 2  # todo-list rendering helper\n"
        "c = 3  # FIXME: a real one\n"
        "d = 4  # TODO fix this\n",
    )
    titles = [c.title for c in from_todos(tmp_path)]
    assert any("a real one" in t for t in titles)  # genuine marker kept
    assert any("fix this" in t for t in titles)  # marker + space kept
    assert not any("style naming" in t for t in titles)  # compound-word prose dropped
    assert not any("rendering helper" in t for t in titles)
