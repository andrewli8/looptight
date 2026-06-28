"""Proposal discovery: turn concrete repo signals into candidate tasks.

The discovery half of task generation scans the working tree for *verifiable*
signals — TODO/FIXME comments, skipped tests, the STATUS "Next" list, lint
findings — and turns each into a :class:`Candidate`. It runs no agent, spends no
tokens, and writes nothing; it only reads the repo.

This is deliberately the cheap, grounded part of "what to work on". The research
behind looptight found free-form task invention is the least validated decision,
so this stays anchored to signals the operating agent can immediately check.
Ranking the discovered candidates is a separate concern (see ``ranking.py``).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

from .grounding import evidence_is_truthful

# Marker inside a real comment token (tokenize gives us only comments, never
# string literals — so a "# TODO" written inside a test fixture string is not a
# false hit).
# Anchored at the start of the comment body, so a marker word merely *mentioned*
# mid-sentence in a comment is not a hit — only conventional "# TODO: ..." lines.
# An optional "(author)" or "[ticket]" attribution (`# TODO(alice):`, `# TODO[#12]:`)
# is allowed and dropped from the title, and an optional leading "@" matches the JSDoc
# `@todo` tag. The marker (or its attribution) must be followed by ':', whitespace, or
# end of line, so a marker-prefixed compound word ("# fixme-style", "@todoize"), a
# plural ("# TODOS:"), or another tag ("@param") is not a hit.
_TODO_RE = re.compile(
    r"^@?(TODO|FIXME|HACK|XXX)(?:\([^)]*\)|\[[^\]]*\])?(?=[:\s]|$)[:\s]*(?P<text>.*)",
    re.IGNORECASE,
)

# The conventional leading ` * ` on a JSDoc/block-comment continuation line, stripped
# so a marker written as ` * TODO: ...` is matched rather than hidden behind the `*`.
_BLOCK_PREFIX_RE = re.compile(r"^\s*\*\s?")


@dataclass(frozen=True)
class Candidate:
    """One proposed task, traceable to the signal that produced it."""

    title: str
    source: str
    location: str | None
    suggested_verify: str | None
    score: float
    detail: str = ""
    acceptance: str = ""

    def render(self) -> str:
        where = f"  [{self.location}]" if self.location else ""
        return f"[{self.source}] {self.title}{where}"


# JavaScript/TypeScript family extensions scanned for TODO markers. Discovery is
# Python-first, but most real repos are polyglot; surfacing JS/TS markers keeps
# the lightweight signal capture useful beyond Python.
_JS_EXTS = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts")


def _files_with_exts(root: Path, subdir: str, exts: tuple[str, ...]) -> list[Path]:
    base = root / subdir
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.rglob("*")
        if p.is_file()
        and p.suffix in exts
        and not (_PRUNE_DIRS & set(p.relative_to(base).parts))
    )


_PRUNE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__",
    ".tox", ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
}


def _not_ignored(root: Path, paths: list[Path]) -> list[Path]:
    """``paths`` with the ones Git ignores removed, so a project's gitignored
    generated/artifact output (`generated/`, `coverage/`, `.next/`, ...) is not
    scanned for markers. Tracked and untracked-but-unignored files (new work in
    progress) are kept. Outside Git or on any git error, every path passes through —
    discovery never depends on Git succeeding."""
    if not paths:
        return paths
    try:
        rels = [p.relative_to(root).as_posix() for p in paths]
    except ValueError:
        return paths
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            input="\n".join(rels), cwd=str(root),
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return paths
    if proc.returncode not in (0, 1):  # 0 = some ignored, 1 = none; else not a repo/error
        return paths
    ignored = set(proc.stdout.splitlines())
    return [p for p, rel in zip(paths, rels) if rel not in ignored]


def _all_py_files(root: Path) -> list[Path]:
    """Every Python file in the project, pruning vendored/build/cache dirs so a big
    repo stays cheap. Layout-agnostic: src-layout (`src/pkg/`), flat packages
    (`pkg/`), and top-level modules (`app.py`) are all covered."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        out += [Path(dirpath) / name for name in filenames if name.endswith(".py")]
    return _not_ignored(root, sorted(out))


def _all_js_files(root: Path) -> list[Path]:
    """Every JS/TS-family file in the project, pruning vendored/build/cache dirs so a
    big repo stays cheap. Layout-agnostic (src/, app/, components/, lib/, pages/, flat),
    matching the Python TODO scan, so a non-src-layout project's markers are not missed."""
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        out += [Path(dirpath) / name for name in filenames if Path(name).suffix in _JS_EXTS]
    return _not_ignored(root, sorted(out))


def _js_test_files(root: Path) -> list[Path]:
    """JS/TS test files anywhere in the tree: `*.test.*`, `*.spec.*`, `*.cy.*`
    (Cypress), or under a `__tests__/` directory. Prunes vendored/build dirs so a big
    repo stays cheap.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        in_tests_dir = "__tests__" in Path(dirpath).parts
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix not in _JS_EXTS:
                continue
            if in_tests_dir or ".test." in name or ".spec." in name or ".cy." in name:
                out.append(path)
    return sorted(out)


def _js_discovery_files(root: Path) -> list[Path]:
    """Deduplicated JS/TS files to scan: everything under `src/`, `tests/`, `test/`
    (Mocha), and `spec/` (Jasmine), plus any colocated test file
    (`*.test.*` / `*.spec.*` / `*.cy.*` / `__tests__/`) elsewhere.
    """
    seen: set[Path] = set()
    files: list[Path] = []
    for sub in ("src", "tests", "test", "spec"):
        for path in _files_with_exts(root, sub, _JS_EXTS):
            if path not in seen:
                seen.add(path)
                files.append(path)
    for path in _js_test_files(root):
        if path not in seen:
            seen.add(path)
            files.append(path)
    return _not_ignored(root, files)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _comments(path: Path):
    """Yield (lineno, comment_text) for real comment tokens, ignoring strings."""
    try:
        with path.open("rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.COMMENT:
                    yield tok.start[0], tok.string
    except (tokenize.TokenError, SyntaxError, OSError, UnicodeDecodeError):
        return


def _multiline_string_lines(path: Path) -> set[int]:
    """Line numbers that are continuation lines of a multi-line string literal, so a
    skip marker written as example text inside a triple-quoted string is not a false
    hit (the Python TODO path already gets this for free via ``tokenize``). Returns
    an empty set on a malformed/unreadable file, leaving detection unchanged."""
    inside: set[int] = set()
    try:
        with path.open("rb") as fh:
            for tok in tokenize.tokenize(fh.readline):
                if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
                    inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
    except (tokenize.TokenError, SyntaxError, OSError, UnicodeDecodeError):
        return set()
    return inside


def _js_line_comment(line: str, in_template: bool = False) -> tuple[str | None, bool, bool]:
    """Scan one line for a `//` or `/* ... */` comment, quote-aware.

    Returns ``(body, block_open, template_open)``: ``body`` is the comment text on
    this line (or None); ``block_open`` is True when a `/*` opened without a closing
    `*/`; ``template_open`` is True when the line ends inside an unclosed backtick
    template literal (a multi-line JS string). ``in_template`` True means the line
    *begins* inside such a literal. The caller threads both flags so a `//`/`/*`
    inside a string, including a multi-line template literal, is never a false hit
    (as the Python path uses ``tokenize``).
    """
    i, n = 0, len(line)
    quote = "`" if in_template else None
    while i < n:
        char = line[i]
        if quote is not None:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "\"'`":
            quote = char
        elif char == "/" and i + 1 < n and line[i + 1] == "/":
            return line[i + 2 :], False, False
        elif char == "/" and i + 1 < n and line[i + 1] == "*":
            end = line.find("*/", i + 2)
            if end == -1:
                return line[i + 2 :], True, False
            return line[i + 2 : end], False, False
        i += 1
    # Only a backtick template literal spans lines; a dangling '/" is a JS syntax
    # error, so we do not propagate it as an open string.
    return None, False, quote == "`"


def _js_comments(path: Path):
    """Yield (lineno, comment_body) for JS/TS line comments and block comments,
    including block comments that span multiple lines."""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    in_block = False
    in_template = False
    for lineno, line in enumerate(lines, 1):
        if in_block:
            end = line.find("*/")
            body = line if end == -1 else line[:end]
            # Strip the conventional JSDoc continuation marker (` * `) so a marker
            # written as ` * TODO: ...` is not hidden behind the leading asterisk.
            yield lineno, _BLOCK_PREFIX_RE.sub("", body, count=1)
            in_block = end == -1  # still open until the closing */
            continue
        body, in_block, in_template = _js_line_comment(line, in_template)
        if body is not None:
            yield lineno, body


#: Cap the extracted marker text so a TODO on a minified/generated/pasted long line
#: cannot become a multi-hundred-KB task that floods host-agent context (the same
#: leanness `next --json` trimming protects). The location still pinpoints the line.
_MAX_MARKER_TEXT = 200

#: Curated `## Next` / task-file items are legitimately paragraph-length (an Evidence pointer
#: and an Acceptance clause), so they get a far more generous cap than the 200-char marker
#: limit — but still bounded, so a pasted/minified multi-hundred-KB line cannot flood host-agent
#: context the way an unbounded curated title/detail/acceptance otherwise would.
_MAX_TASK_TEXT = 4000


def _bound(text: str, limit: int = _MAX_MARKER_TEXT) -> str:
    """Truncate overlong extracted text to a sane length with an ellipsis."""
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _todo_candidate(root: Path, path: Path, lineno: int, body: str, detail: str) -> Candidate | None:
    """Build a `todo` candidate from a comment body, or None if it is not a marker."""
    match = _TODO_RE.match(body.strip())
    if not match:
        return None
    text = match.group("text").strip() or match.group(1).upper()
    location = f"{_rel(root, path)}:{lineno}"
    return Candidate(
        title=_bound(text),
        source="todo",
        location=location,
        suggested_verify=None,
        score=0.0,
        detail=_bound(detail.strip()),
        acceptance=f"Remove the marker at {location} and pass project verification.",
    )


def from_todos(root: Path) -> list[Candidate]:
    """TODO/FIXME/HACK/XXX in real comments (not string literals) across Python and JS/TS."""
    out: list[Candidate] = []
    for path in _all_py_files(root):
        for lineno, comment in _comments(path):
            candidate = _todo_candidate(root, path, lineno, comment.lstrip("#"), comment)
            if candidate is not None:
                out.append(candidate)
    for path in _all_js_files(root):
        for lineno, body in _js_comments(path):
            candidate = _todo_candidate(root, path, lineno, body, body)
            if candidate is not None:
                out.append(candidate)
    return out


def _is_skip_line(stripped: str) -> bool:
    """True for real skip/xfail code, not a marker string inside a literal.

    Covers pytest (`@pytest.mark.skip/xfail`, imperative `pytest.skip(...)`/
    `pytest.xfail(...)`, `pytestmark = ...`) and stdlib unittest
    (`@unittest.skip/skipIf/skipUnless`, `self.skipTest(...)`). The shared env-gate
    and conditional-guard classifiers below decide which of the conditional forms are
    intentional infrastructure versus rot.
    """
    if stripped.startswith((
        "@pytest.mark.skip", "@pytest.mark.xfail", "pytest.skip(", "pytest.xfail(",
        "@unittest.skip", "self.skipTest(",
    )):
        return True
    if re.match(r"\w+\s*=\s*pytest\.mark\.(?:skip|skipif|xfail)\b", stripped):
        return True
    # A single-line parametrize case disabled inline: `pytest.param(.., marks=
    # pytest.mark.skip(..))`. Strip strings and a trailing comment first so a marker
    # merely mentioned in a comment or string is not a false hit. Gated by a cheap
    # substring test so the regex runs only on plausible lines.
    if "marks" in stripped and "pytest.mark." in stripped:
        code = _code_only(stripped).split("#", 1)[0]
        return bool(re.search(r"\bmarks\s*=.*\bpytest\.mark\.(?:skip|skipif|xfail)\b", code))
    return False


# An env-var gate (`skipif(not os.environ.get(...))`) marks an opt-in eval —
# intentional infrastructure, not a bit-rotting skip — so it is not a fix-me.
_OPTIN_RE = re.compile(r"os\.environ|os\.getenv|\benviron\b")

# Quoted string literals are data, not code: a marker word inside a skip *reason*
# message ("os.environ setup is broken") must not be read as an env-var gate. We
# strip literals before the gate check, mirroring how comment scanning above
# tokenizes precisely so a marker mentioned inside a string never counts.
_STRING_LITERAL_RE = re.compile(
    r"[rRbBuUfF]{0,3}"
    r'(?:"""(?:\\.|[^\\])*?"""'
    r"|'''(?:\\.|[^\\])*?'''"
    r'|"(?:\\.|[^"\\])*"'
    r"|'(?:\\.|[^'\\])*')",
    re.DOTALL,
)


def _code_only(text: str) -> str:
    """``text`` with quoted string literals removed, leaving only code."""
    return _STRING_LITERAL_RE.sub("", text)


def _statement_text(lines: list[str], start: int) -> str:
    """Join lines from ``start`` until parentheses balance — the full marker call.

    Lets us see a condition that wraps onto following lines (the common shape of
    `pytestmark = pytest.mark.skipif(\\n    not os.environ.get(...))`). Parens inside
    string literals (e.g. an unbalanced `(` in a skip ``reason="..."``) are ignored,
    so a quirky reason message cannot over-extend the statement into later lines and
    make the env-gate classifier swallow an unrelated skip.
    """
    depth = 0
    chunk: list[str] = []
    for line in lines[start:]:
        chunk.append(line)
        code = _code_only(line)
        depth += code.count("(") - code.count(")")
        if depth <= 0:
            break
    return "\n".join(chunk)


def _inside_conditional(lines: list[str], idx: int) -> bool:
    """True if ``lines[idx]`` sits inside an ``if`` / ``elif`` guard.

    An imperative ``pytest.skip()`` reached only under a runtime guard is a
    conditional skip — the test runs whenever the guard is false (the normal CI
    case) — so it is intentional infrastructure (a capability or platform gate),
    not a bit-rotting skip to fix. We look at the immediately enclosing block.
    """
    indent = len(lines[idx]) - len(lines[idx].lstrip())
    for prev in reversed(lines[:idx]):
        if not prev.strip():
            continue
        if len(prev) - len(prev.lstrip()) < indent:
            return bool(re.match(r"(if|elif)\b", prev.strip()))
    return False


def _module_is_optin(lines: list[str]) -> bool:
    """True if the whole module is gated behind an env-var ``pytestmark`` skipif.

    Such a module is an opt-in eval wholesale; nothing in it is rot to fix, so we
    surface no candidates for it at all (including inner ``pytest.skip`` guards).
    """
    for idx, line in enumerate(lines):
        if re.match(r"pytestmark\s*=\s*pytest\.mark\.skipif\b", line.strip()):
            if _OPTIN_RE.search(_code_only(_statement_text(lines, idx))):
                return True
    return False


# JS/TS test skips: `it.skip(`, `describe.skip(`, `test.skip(`, `test.todo(`,
# and the `xit(` / `xdescribe(` / `xtest(` shorthands (Jest aliases for the
# `.skip` forms). JS has no env-gate opt-in convention like pytest, so detection
# is a plain marker match on code (string literals stripped) outside comment lines.
# `skip`/`todo` may sit anywhere in the `.`-chain after it/describe/test, so chained
# Jest/Vitest forms (`test.concurrent.skip(`, `it.skip.each(`) are caught; the chain
# segments keep `skip` a whole token so `it.skipFoo(`/`skipped` and `it.only` are not
# false hits. The `x`-prefix forms (`xit`/`xdescribe`/`xtest`) stay separate.
_JS_SKIP_CALL = r"(?:x(?:it|describe|test)|(?:it|describe|test)(?:\.\w+)*\.(?:skip|todo|fixme|failing|fails)(?:\.\w+)*)"
_JS_SKIP_RE = re.compile(rf"\b{_JS_SKIP_CALL}\s*\(")
# Capture the test name to the matching closing quote of the *same* type as the
# opener (backreference), so a nested quote of a different type — an apostrophe in a
# double-quoted name, ubiquitous in test descriptions — is kept whole, not truncated.
_JS_SKIP_NAME_RE = re.compile(
    rf"\b{_JS_SKIP_CALL}\s*\(\s*"
    r"(?P<q>[\"'`])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)"
)


def _js_skip_candidate(root: Path, path: Path, lineno: int, line: str) -> Candidate | None:
    """Build a `skipped-test` candidate from a JS/TS skip marker, or None."""
    stripped = line.strip()
    if stripped.startswith(("//", "*", "/*")):  # comment line, not code
        return None
    # Strip string literals (via _code_only) AND any trailing // or /* comment, so a
    # skip marker mentioned in a comment on a code line is not a false hit. A // or /*
    # surviving in code-only text is a real comment (strings are already removed).
    code = _code_only(line)
    for marker in ("//", "/*"):
        cut = code.find(marker)
        if cut != -1:
            code = code[:cut]
    if not _JS_SKIP_RE.search(code):  # marker only inside a string/comment, or absent
        return None
    name_match = _JS_SKIP_NAME_RE.search(line)
    # An empty name (`it.skip("")`) falls back to a generic label, as before.
    name = (name_match.group("name").strip() if name_match else "") or "skipped test"
    location = f"{_rel(root, path)}:{lineno}"
    return Candidate(
        title=_bound(f"un-skip / fix skipped test: {name}"),
        source="skipped-test",
        location=location,
        suggested_verify=None,
        score=0.0,
        detail=stripped,
        acceptance=f"Re-enable the test at {location} without skip and pass project verification.",
    )


def from_skipped_tests(root: Path) -> list[Candidate]:
    """Skipped / xfailed tests — each is a candidate to fix and re-enable.

    Env-gated opt-in evals (`skipif(not os.environ.get(...))`) are skipped: they
    are deliberate infrastructure, so surfacing them every run is just noise.
    """
    out: list[Candidate] = []
    for path in _all_py_files(root):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if _module_is_optin(lines):
            continue
        string_lines = _multiline_string_lines(path)
        for idx, line in enumerate(lines):
            if idx + 1 in string_lines:  # a marker inside a multi-line string is example text
                continue
            stripped = line.strip()
            if not _is_skip_line(stripped):
                continue
            if _OPTIN_RE.search(_code_only(_statement_text(lines, idx))):
                continue
            if stripped.startswith(("pytest.skip(", "pytest.xfail(", "self.skipTest(")) and _inside_conditional(lines, idx):
                continue
            out.append(
                Candidate(
                    title=f"un-skip / fix skipped test in {path.name}",
                    source="skipped-test",
                    location=f"{_rel(root, path)}:{idx + 1}",
                    suggested_verify=None,
                    score=0.0,
                    detail=line.strip(),
                    acceptance="Run this test without skip/xfail and pass project verification.",
                )
            )
    for path in _js_discovery_files(root):
        in_block = False
        in_template = False
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
        ):
            if in_block:  # inside a multi-line /* */ comment: not code
                in_block = line.find("*/") == -1
                continue
            began_in_template = in_template
            _body, in_block, in_template = _js_line_comment(line, in_template)
            if began_in_template:
                continue  # line begins inside a multi-line template literal: string text
            candidate = _js_skip_candidate(root, path, lineno, line)
            if candidate is not None:
                out.append(candidate)
    return out


def from_task_file(
    root: Path,
    task_file: str,
    *,
    next_section_only: bool = False,
    enforce_truthful_evidence: bool = False,
    cap: int | None = 6,
) -> list[Candidate]:
    """Return executable numbered tasks from one explicit repository file.

    With ``enforce_truthful_evidence``, an item whose named ``Evidence:`` anchors do
    not all resolve to real files is dropped (the grounding gate for generated
    tasks); items naming no anchor are kept, so hand-written lists are unaffected.

    ``cap`` bounds the number of tasks returned (default 6, the documented maximum the
    ``next``/``propose`` path enforces). Pass ``cap=None`` to read the *true* count —
    the eval needs every task to judge whether the batch exceeded the 1-6 bound.
    """
    relative = Path(task_file)
    if relative.is_absolute() or ".." in relative.parts:
        return []
    path = root / relative
    if not path.is_file():
        return []
    out: list[Candidate] = []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    in_next = not next_section_only
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("## "):
            if next_section_only:
                in_next = stripped[3:].strip().lower() == "next"
            idx += 1
            continue
        if not in_next:
            idx += 1
            continue
        # Accept both `1.` and `1)` ordered-list markers (idiomatic markdown).
        item = re.match(r"\d+[.)]\s+(?P<text>.+)", stripped)
        if not item:
            idx += 1
            continue
        item_lineno = idx + 1
        # A numbered item may wrap onto following indented lines; join them so the
        # candidate title is the whole entry, not a mid-sentence truncation.
        parts = [item.group("text").strip()]
        idx += 1
        while idx < len(lines):
            nxt = lines[idx]
            nxt_stripped = nxt.strip()
            if not nxt_stripped or nxt[:1] not in (" ", "\t"):
                break
            if nxt_stripped.startswith("## ") or re.match(r"\d+[.)]\s+", nxt_stripped):
                break
            parts.append(nxt_stripped)
            idx += 1
        text = " ".join(parts)
        if text.startswith("~~"):
            continue
        task_text, marker, acceptance = text.partition("Acceptance:")
        if not marker or not task_text.strip() or not acceptance.strip():
            continue
        if enforce_truthful_evidence and not evidence_is_truthful(root, text):
            continue  # claims evidence that does not resolve: a grounding-gate drop
        out.append(
            Candidate(
                title=_bound(task_text.strip().rstrip(".;"), _MAX_TASK_TEXT),
                source="status-next" if next_section_only else "task-file",
                location=f"{relative.as_posix()}:{item_lineno}",
                suggested_verify=None,
                score=0.0,
                detail=_bound(text, _MAX_TASK_TEXT),
                acceptance=_bound(acceptance.strip(), _MAX_TASK_TEXT),
            )
        )
        if cap is not None and len(out) >= cap:
            return out
    return out


def from_status_next(
    root: Path, *, cap: int | None = 6, enforce_truthful_evidence: bool = True
) -> list[Candidate]:
    """Return the executable tasks under the status Next heading (at most ``cap``).

    This is the generated/planned queue. By default its evidence anchors are enforced: an
    item claiming evidence that does not resolve is dropped as ungrounded busywork — what the
    ``next``/``propose`` claim path wants. The idea-evaluation path passes
    ``enforce_truthful_evidence=False`` instead, so it scores the *raw* batch the host wrote
    (and lets ``score_batch`` measure groundedness itself) rather than a pre-filtered subset.
    ``cap`` defaults to the documented six-task maximum; ``cap=None`` reads the true count.
    """
    return from_task_file(
        root,
        "docs/STATUS.md",
        next_section_only=True,
        enforce_truthful_evidence=enforce_truthful_evidence,
        cap=cap,
    )


def from_lint(root: Path) -> list[Candidate]:
    """ruff findings, one task per (file, rule). Empty when ruff is unavailable."""
    ruff = shutil.which("ruff")
    if ruff is None:
        return []
    cmd = [ruff, "check", "--no-cache", "--output-format", "concise", "--quiet"]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[Candidate] = []
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        # ruff default format: path:line:col: CODE message
        match = re.match(r"(?P<loc>\S+:\d+:\d+):\s+(?P<code>\S+)\s+(?P<msg>.+)", line)
        if not match:
            continue
        key = f"{match.group('loc').split(':')[0]}:{match.group('code')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Candidate(
                title=f"fix {match.group('code')}: {match.group('msg')}",
                source="lint",
                location=match.group("loc"),
                suggested_verify="ruff check",
                score=0.0,
                detail=line.strip(),
                acceptance=f"Remove {match.group('code')} at {match.group('loc')} and pass ruff check.",
            )
        )
    return out


_EXTRACTORS = (from_lint, from_skipped_tests, from_todos, from_status_next)


def discover(root: Path, *, task_files: tuple[str, ...] = ()) -> list[Candidate]:
    """Read explicit task files, or fall back to the built-in signal extractors."""
    if task_files:
        # Enforce truthful evidence on configured task-files too: a task claiming an
        # Evidence anchor that does not resolve is ungrounded busywork regardless of
        # source (this is the anti-fabrication gate). Unanchored items are kept.
        return [
            candidate
            for task_file in task_files
            for candidate in from_task_file(root, task_file, enforce_truthful_evidence=True)
        ]
    found: list[Candidate] = []
    for extractor in _EXTRACTORS:
        found.extend(extractor(root))
    return found
