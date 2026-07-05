"""Shared, dependency-free grounding checks for a task's evidence anchors.

A generated task is supposed to cite ``Evidence: path[:line]`` that points at a
real repository file. Two predicates over the raw task text express the two uses:

- ``is_grounded`` (strict): names at least one anchor and every one resolves.
  The *ideal*, used by the idea eval to measure batch quality.
- ``evidence_is_truthful`` (lenient): every named anchor resolves, vacuously true
  when none is named. The *gate*, used to reject a generated task whose claimed
  evidence is fabricated or stale, without dropping a legacy item that simply
  names no anchor.

One source so the discovery gate and the eval cannot drift. No model or network
calls; pure functions over the text and the working tree.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "evidence_refs", "ref_resolves", "is_grounded", "evidence_is_truthful",
    "strip_anchor_decoration", "strip_position_suffix",
]

# One path token per ``Evidence:`` marker. After the marker, skip whitespace and
# any markdown emphasis a writer wraps the label in (``**Evidence:**``, ``*…*``)
# before the path; otherwise the closing ``**`` is captured as the anchor and the
# real path is missed. Then take either a backtick-delimited code span — whose
# backticks delimit the path, so a space inside it (``my src/a file.py:1``) is part
# of the path — or, when undecorated, a bare token that ends at the first
# whitespace, ``;`` or ``,`` (which begin a following clause or prose). Cite
# multiple files with multiple ``Evidence:`` markers, not a list.
# The negative lookbehind ``(?<!`)`` prevents matching ``Evidence:`` when it is
# itself inside a backtick code span (e.g. "names no ``Evidence:`` anchor"), which
# would otherwise cause the regex to capture the following text as a false anchor.
_EVIDENCE_RE = re.compile(r"(?<!`)\bEvidence:[\s*]*(?:`([^`]+)`|([^\s;,`*]+))")


def strip_anchor_decoration(ref: str) -> str:
    """An evidence anchor with idiomatic decoration removed: a markdown code span
    (`` `path` ``, how this repo's STATUS.md and LLM-generated tasks write anchors)
    and a trailing sentence period. A *leading* dot is meaningful (``./path``,
    ``.dotfile``) and is preserved. Shared by the gate and the swarm planner so
    the tolerance is defined and tested in exactly one place (it has drifted)."""
    return ref.strip("`").rstrip(".").rstrip("`")


def evidence_refs(text: str) -> list[str]:
    """Every ``Evidence:`` anchor named in a task's text (``path`` or ``path:line``).

    Surrounding markdown code-span backticks are stripped so the anchor is the
    bare path for every consumer (the resolver and the diversity metric alike).
    """
    # Each match yields (code-span, bare-token); exactly one group is populated.
    return [(span or bare).strip("`") for span, bare in _EVIDENCE_RE.findall(text or "")]


# A trailing position: one or more ``:N`` groups, each an optional ``-N`` range.
# Covers ``path:line``, ``path:line:col`` (a lint location), and the idiomatic
# ``path:start-end`` line range, so none is mistaken for part of the file path.
_POSITION_SUFFIX = re.compile(r"(:\d+(?:-\d+)?)+$")


def strip_position_suffix(path: str) -> str:
    """Drop a trailing ``:line`` / ``:line:col`` / ``:start-end`` position from a path
    so it is position-stable. One definition so every position-stable consumer (the
    grounding resolver and the idea identity) shares the same range-aware rule and the
    two cannot drift."""
    return _POSITION_SUFFIX.sub("", path)


def ref_resolves(root: Path, ref: str) -> bool:
    """True when an evidence ref points at a real file inside the repository."""
    # Strip idiomatic decoration, then drop a trailing position suffix so `path`,
    # `path:line`, `path:line:col` (a lint location), and `path:start-end` (a line
    # range) all resolve to the same file.
    path_text = strip_position_suffix(strip_anchor_decoration(ref))
    relative = Path(path_text)
    if not path_text or relative.is_absolute() or ".." in relative.parts:
        return False
    return (root / relative).is_file()


def is_grounded(root: Path, text: str) -> bool:
    """Strict: names at least one evidence anchor and every one resolves to a file."""
    refs = evidence_refs(text)
    return bool(refs) and all(ref_resolves(root, ref) for ref in refs)


def evidence_is_truthful(root: Path, text: str) -> bool:
    """Lenient: every named evidence anchor resolves; vacuously true when none is
    named. Rejects fabricated/stale evidence while sparing an unanchored item."""
    return all(ref_resolves(root, ref) for ref in evidence_refs(text))
