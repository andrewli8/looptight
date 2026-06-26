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

__all__ = ["evidence_refs", "ref_resolves", "is_grounded", "evidence_is_truthful"]

# One path token per ``Evidence:`` marker. A path carries no spaces, so the token
# ends at the first whitespace, ``;`` or ``,`` (which begin a following clause or
# prose). Cite multiple files with multiple ``Evidence:`` markers, not a list.
_EVIDENCE_RE = re.compile(r"\bEvidence:\s*([^\s;,]+)")


def evidence_refs(text: str) -> list[str]:
    """Every ``Evidence:`` anchor named in a task's text (``path`` or ``path:line``)."""
    return _EVIDENCE_RE.findall(text or "")


_POSITION_SUFFIX = re.compile(r"(:\d+)+$")


def ref_resolves(root: Path, ref: str) -> bool:
    """True when an evidence ref points at a real file inside the repository."""
    # Tolerate idiomatic decoration first — a markdown code span
    # (``Evidence: `path` ``, as this repo's own STATUS.md writes anchors) and a
    # trailing sentence period — then drop a trailing position suffix so `path`,
    # `path:line`, and `path:line:col` (e.g. a lint location) all resolve.
    path_text = _POSITION_SUFFIX.sub("", ref.strip("`."))
    path_text = path_text.rstrip("`.")  # any residual wrapper revealed by the strip
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
