"""A stable, deliberately lossy identity for an idea (a discovery candidate).

Distinct from the line-precise claim fingerprint in tasks.py. Outcomes are keyed
on this so that the same idea proposed again is recognized even when a line moves
or a tool's message is reworded, while different ideas stay distinct. Both the
write path (recording outcomes) and the read path (the self-model) compute it
here so the two cannot drift.
"""

from __future__ import annotations

import hashlib
import re

from .discovery import Candidate

_LINT_RULE_RE = re.compile(r"\bfix\s+([A-Z]+[0-9]+)\b", re.IGNORECASE)
_CURATED = {"status-next", "task-file"}


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _path(location: str | None) -> str:
    if not location:
        return ""
    return location.rsplit(":", 1)[0]  # drop a trailing :line if present


def _identity_tuple(candidate: Candidate) -> tuple[str, ...]:
    source, location, title = candidate.source, candidate.location, candidate.title
    if source == "lint":
        match = _LINT_RULE_RE.search(title)
        rule = match.group(1).upper() if match else _normalized(title)
        return ("lint", _path(location), rule)
    if source == "todo":
        return ("todo", _path(location), _normalized(title))
    if source == "skipped-test":
        return ("skipped-test", _normalized(title))
    if source in _CURATED:
        return ("curated", _normalized(title))
    return (source, _path(location), _normalized(title))


def idea_id(candidate: Candidate) -> str:
    """Return the lossy idea identity for a candidate (12-char hex)."""
    joined = "\0".join(_identity_tuple(candidate))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
