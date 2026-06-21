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

import re
import shutil
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

# Marker inside a real comment token (tokenize gives us only comments, never
# string literals — so a "# TODO" written inside a test fixture string is not a
# false hit).
# Anchored at the start of the comment body, so a marker word merely *mentioned*
# mid-sentence in a comment is not a hit — only conventional "# TODO: ..." lines.
_TODO_RE = re.compile(r"^(TODO|FIXME|HACK|XXX)\b[:\s]*(?P<text>.*)", re.IGNORECASE)


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


def _py_files(root: Path, subdir: str) -> list[Path]:
    base = root / subdir
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if p.is_file())


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


def from_todos(root: Path) -> list[Candidate]:
    """TODO/FIXME/HACK/XXX in real comments (not string literals), with file:line."""
    out: list[Candidate] = []
    for sub in ("src", "tests"):
        for path in _py_files(root, sub):
            for lineno, comment in _comments(path):
                match = _TODO_RE.match(comment.lstrip("#").strip())
                if not match:
                    continue
                text = match.group("text").strip() or match.group(1).upper()
                out.append(
                    Candidate(
                        title=text,
                        source="todo",
                        location=f"{_rel(root, path)}:{lineno}",
                        suggested_verify=None,
                        score=0.0,
                        detail=comment.strip(),
                        acceptance=f"Remove the marker at {_rel(root, path)}:{lineno} and pass project verification.",
                    )
                )
    return out


def _is_skip_line(stripped: str) -> bool:
    """True for real skip/xfail code, not a marker string inside a literal."""
    if stripped.startswith(("@pytest.mark.skip", "@pytest.mark.xfail", "pytest.skip(")):
        return True
    return bool(re.match(r"\w+\s*=\s*pytest\.mark\.(?:skip|skipif|xfail)\b", stripped))


# An env-var gate (`skipif(not os.environ.get(...))`) marks an opt-in eval —
# intentional infrastructure, not a bit-rotting skip — so it is not a fix-me.
_OPTIN_RE = re.compile(r"os\.environ|os\.getenv|\benviron\b")


def _statement_text(lines: list[str], start: int) -> str:
    """Join lines from ``start`` until parentheses balance — the full marker call.

    Lets us see a condition that wraps onto following lines (the common shape of
    `pytestmark = pytest.mark.skipif(\\n    not os.environ.get(...))`).
    """
    depth = 0
    chunk: list[str] = []
    for line in lines[start:]:
        chunk.append(line)
        depth += line.count("(") - line.count(")")
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
            if _OPTIN_RE.search(_statement_text(lines, idx)):
                return True
    return False


def from_skipped_tests(root: Path) -> list[Candidate]:
    """Skipped / xfailed tests — each is a candidate to fix and re-enable.

    Env-gated opt-in evals (`skipif(not os.environ.get(...))`) are skipped: they
    are deliberate infrastructure, so surfacing them every run is just noise.
    """
    out: list[Candidate] = []
    for path in _py_files(root, "tests"):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if _module_is_optin(lines):
            continue
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not _is_skip_line(stripped):
                continue
            if _OPTIN_RE.search(_statement_text(lines, idx)):
                continue
            if stripped.startswith("pytest.skip(") and _inside_conditional(lines, idx):
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
    return out


def from_task_file(root: Path, task_file: str, *, next_section_only: bool = False) -> list[Candidate]:
    """Return executable numbered tasks from one explicit repository file."""
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
        item = re.match(r"\d+\.\s+(?P<text>.+)", stripped)
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
            if nxt_stripped.startswith("## ") or re.match(r"\d+\.\s+", nxt_stripped):
                break
            parts.append(nxt_stripped)
            idx += 1
        text = " ".join(parts)
        if text.startswith("~~"):
            continue
        task_text, marker, acceptance = text.partition("Acceptance:")
        if not marker or not task_text.strip() or not acceptance.strip():
            continue
        out.append(
            Candidate(
                title=task_text.strip().rstrip(".;"),
                source="status-next" if next_section_only else "task-file",
                location=f"{relative.as_posix()}:{item_lineno}",
                suggested_verify=None,
                score=0.0,
                detail=text,
                acceptance=acceptance.strip(),
            )
        )
        if len(out) == 6:
            return out
    return out


def from_status_next(root: Path) -> list[Candidate]:
    """Return at most the first six executable tasks under the status Next heading."""
    return from_task_file(root, "docs/STATUS.md", next_section_only=True)


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
        return [
            candidate
            for task_file in task_files
            for candidate in from_task_file(root, task_file)
        ]
    found: list[Candidate] = []
    for extractor in _EXTRACTORS:
        found.extend(extractor(root))
    return found
