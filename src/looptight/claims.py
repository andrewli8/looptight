"""Private, atomic task claims shared by a repository's worktrees."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

_STALE_AFTER_S = 24 * 60 * 60


def _claimed_at(claim: dict[str, object]) -> float:
    """Claim timestamp as a float, or 0.0 (long-expired) when unparseable, so a
    corrupt/hand-edited claim is pruned rather than crashing the reader."""
    try:
        return float(claim.get("claimed_at", 0))
    except (TypeError, ValueError):
        return 0.0

#: Written under ``<git-common>/looptight`` once a repository is migrated to the
#: SQLite coordinator; legacy file claims then fail closed.
MARKER_NAME = "coordinator-format.json"


class LegacyClaimsDisabled(RuntimeError):
    """Raised when legacy file claims are used after coordinator activation."""


def has_live_claim(claims_root: Path, *, now: float | None = None) -> bool:
    """True if ``claims_root`` holds at least one unexpired legacy claim."""
    if not claims_root.is_dir():
        return False
    timestamp = time.time() if now is None else now
    for path in claims_root.glob("*.json"):
        claim = ClaimStore._read(path)
        if claim and timestamp - _claimed_at(claim) <= _STALE_AFTER_S:
            return True
    return False


def claim_dir(workdir: Path) -> Path | None:
    """Return Git-private shared state, or None outside a Git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=workdir,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # headless-safe: never block on a prompt
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = workdir / path
    return path.resolve() / "looptight" / "claims"


def owner_id(workdir: Path) -> str:
    """A stable owner per worktree; parallel sessions must use separate trees."""
    explicit = os.environ.get("LOOPTIGHT_SESSION_ID")
    if explicit:
        return explicit
    return f"{socket.gethostname()}:{workdir.resolve()}"


class ClaimStore:
    def __init__(self, root: Path, owner: str, *, now: float | None = None) -> None:
        self.root = root
        self.owner = owner
        self.now = time.time() if now is None else now

    def _fail_closed_if_migrated(self) -> None:
        if (self.root.parent / MARKER_NAME).exists():
            raise LegacyClaimsDisabled(
                "repository migrated to the coordinator; legacy file claims are disabled"
            )

    def select(self, tasks: list[dict[str, str | None]]) -> dict[str, str | None] | None:
        """Return this owner's active task or atomically claim the first free one."""
        self._fail_closed_if_migrated()
        self.root.mkdir(parents=True, exist_ok=True)
        active = {task["id"]: task for task in tasks}

        for path in self.root.glob("*.json"):
            claim = self._read(path)
            task_id = claim.get("task_id") if claim else None
            expired = not claim or self.now - _claimed_at(claim) > _STALE_AFTER_S
            if expired or not isinstance(task_id, str) or task_id not in active:
                path.unlink(missing_ok=True)
                continue
            if claim.get("owner") == self.owner:
                return active[task_id]

        for task in tasks:
            if self._claim(task["id"]):
                return task
        return None

    def summary(self) -> tuple[str | None, int]:
        """Return this owner's task ID and total live claims without mutation."""
        self._fail_closed_if_migrated()
        owned: str | None = None
        active = 0
        if not self.root.is_dir():
            return owned, active
        for path in self.root.glob("*.json"):
            claim = self._read(path)
            if not claim or self.now - _claimed_at(claim) > _STALE_AFTER_S:
                continue
            active += 1
            if claim.get("owner") == self.owner:
                value = claim.get("task_id")
                owned = value if isinstance(value, str) else None
        return owned, active

    def _claim(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        path = self.root / f"{task_id}.json"
        payload = json.dumps(
            {"schema_version": 1, "task_id": task_id, "owner": self.owner, "claimed_at": self.now},
            sort_keys=True,
        ).encode()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        return True

    @staticmethod
    def _read(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
