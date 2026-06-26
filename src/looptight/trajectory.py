"""Repo-private, per-worktree verify-trajectory store (session-native stall).

The headless run loop keeps the value-aware stopping signal in memory across
iterations. The session-native path runs each ``verify`` as a separate process,
so to detect a stall there we persist the progress signal (and the failures
behind it) between calls in a Git-private, per-worktree file.

Opt-in: only written when ``verify --patience`` is set, so the default ``verify``
contract is unchanged. Per-worktree (keyed on ``--git-dir``, not the shared
``--git-common-dir``) so parallel worktrees never share a trajectory. Tolerant
reads and atomic writes, matching goal.py / ui.py.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from .fsutil import atomic_write_text

_FILE = "verify-trajectory.json"
_STALE_AFTER_S = 30 * 60  # an older trajectory is a different attempt; reset
SCHEMA_VERSION = 1


def _path(root: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    git_dir = Path(result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    return git_dir / "looptight" / _FILE


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # absent or corrupt/non-UTF-8 -> treat as no prior attempt
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    return data


def _write(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, sort_keys=True) + "\n")


def clear(root: Path) -> None:
    """Drop the current attempt's trajectory."""
    path = _path(root)
    if path is not None:
        path.unlink(missing_ok=True)


def _is_fresh(prior: dict | None, command: str, now: float) -> bool:
    """True when ``prior`` belongs to the same ongoing attempt: same verify
    command and recent. A non-numeric timestamp is treated as stale."""
    if prior is None or prior.get("command") != command:
        return False
    try:
        age = now - float(prior.get("updated_at", 0))
    except (TypeError, ValueError):
        return False
    return age <= _STALE_AFTER_S


def record(
    root: Path,
    command: str,
    signal: float | None,
    failures: set[str],
    *,
    passed: bool,
    now: float | None = None,
) -> list[dict]:
    """Record one verify outcome and return the attempt's entries (oldest first).

    A passing verify clears the attempt and returns ``[]``. Otherwise the entry
    ``{"signal", "failures"}`` is appended, after resetting when the verify command
    changed or the prior entry is stale. A no-op (returns ``[]``) outside Git.
    """
    path = _path(root)
    if path is None:
        return []
    if passed:
        path.unlink(missing_ok=True)
        return []
    now = time.time() if now is None else now
    prior = _read(path)
    entries = (
        list(prior["entries"])
        if _is_fresh(prior, command, now) and isinstance(prior.get("entries"), list)
        else []
    )
    entries.append({"signal": signal, "failures": sorted(failures)})
    _write(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "updated_at": now,
            "entries": entries,
        },
    )
    return entries
