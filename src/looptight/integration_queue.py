"""Repository-local integration serialization.

A repository-private advisory lock guards one coordinator-owned *detached*
integration worktree, so concurrent Looptight sessions serialize only the Git
integration step while planning and worker execution stay parallel. Stdlib-only;
all state lives under the Git common directory, and user-created worktrees are
never touched.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if os.name == "nt":  # pragma: no cover - exercised on Windows only
    import msvcrt
else:
    import fcntl

_LOCK_NAME = "integration.lock"
_POLL_INTERVAL_S = 0.01


class CoordinationTimeout(Exception):
    """Raised when the integration lock cannot be acquired within the timeout."""


class IntegrationError(Exception):
    """Raised when a coordinator integration worktree cannot be prepared safely."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def git_common_dir(root: Path) -> Path:
    """Resolve the repository's shared Git common directory."""
    result = _git(root, "rev-parse", "--git-common-dir")
    if result.returncode != 0:
        raise IntegrationError(result.stderr.strip() or "not a Git repository")
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve()


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":  # pragma: no cover - Windows only
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - Windows only
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class IntegrationLock:
    """A held repository integration lock; closing the fd releases it on crash."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    @contextmanager
    def acquire(cls, common_dir: Path, timeout_s: float) -> Iterator["IntegrationLock"]:
        """Hold an exclusive advisory lock under ``common_dir`` or time out.

        Polls a non-blocking OS lock until ``timeout_s`` elapses. The descriptor
        is closed on exit, so a crashed holder releases the lock automatically.
        """
        directory = Path(common_dir) / "looptight"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _LOCK_NAME
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + max(0.0, timeout_s)
        locked = False
        try:
            while True:
                locked = _try_lock(fd)
                if locked:
                    break
                if time.monotonic() >= deadline:
                    raise CoordinationTimeout(f"integration lock busy: {path}")
                time.sleep(_POLL_INTERVAL_S)
            yield cls(path)
        finally:
            if locked:
                _unlock(fd)
            os.close(fd)


def integration_worktree(root: Path, target_ref: str) -> Path:
    """Return the coordinator-owned integration worktree path for ``target_ref``."""
    digest = hashlib.sha256(target_ref.encode("utf-8")).hexdigest()[:16]
    return git_common_dir(root) / "looptight" / "integration" / digest


def prepare_integration_worktree(root: Path, target_ref: str) -> tuple[Path, str]:
    """Create/validate a clean detached worktree for integrating ``target_ref``.

    Returns ``(path, observed_sha)``. Refuses to operate on any path outside the
    coordinator integration directory and never resets a user worktree.
    """
    common = git_common_dir(root)
    resolved = _git(root, "rev-parse", "--verify", f"{target_ref}^{{commit}}")
    if resolved.returncode != 0:
        raise IntegrationError(resolved.stderr.strip() or f"cannot resolve {target_ref}")
    sha = resolved.stdout.strip()
    path = integration_worktree(root, target_ref)
    base = (common / "looptight" / "integration").resolve()
    if not path.resolve().is_relative_to(base):
        raise IntegrationError("integration worktree escaped the coordinator directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        added = _git(root, "worktree", "add", "--detach", str(path), sha)
        if added.returncode != 0:
            raise IntegrationError(added.stderr.strip() or "could not create integration worktree")
    if git_common_dir(path) != common:
        raise IntegrationError("integration worktree belongs to a different repository")
    status = _git(path, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        raise IntegrationError("integration worktree is not clean")
    return path, sha
