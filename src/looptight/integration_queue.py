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

from .coordinator import Coordinator, IntegrationOutcome, IntegrationRecord
from .verify import run_verify

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
    # Sync a reused worktree to the current target tip so each integration starts
    # from the observed base. The worktree is coordinator-owned, never a user one.
    reset = _git(path, "reset", "--hard", sha)
    if reset.returncode != 0:
        raise IntegrationError(reset.stderr.strip() or "could not reset integration worktree")
    _git(path, "clean", "-qfd")
    return path, sha


class Integrator:
    """Drain queued integrations one at a time, under the repository lock.

    Each record is fenced to its lease generation: a record whose lease has since
    been reassigned is ``superseded`` (the new owner keeps its lease). Otherwise the
    candidate is merged into a coordinator-owned worktree, verified, and the target
    ref advanced with a compare-and-swap against the observed tip.
    """

    def __init__(self, coordinator: Coordinator, *, lock_timeout_s: float = 300.0, max_attempts: int = 3) -> None:
        self.coordinator = coordinator
        self.lock_timeout_s = lock_timeout_s
        self.max_attempts = max_attempts

    def next_id(self) -> str | None:
        record = self.coordinator.next_queued_integration()
        return record.id if record else None

    def run_next(self, root: Path, verify: str) -> IntegrationOutcome | None:
        with IntegrationLock.acquire(git_common_dir(root), self.lock_timeout_s):
            record = self.coordinator.next_queued_integration()
            if record is None:
                return None
            return self._run(record, root, verify)

    def run_record(
        self, record: IntegrationRecord, root: Path | None = None, verify: str | None = None
    ) -> IntegrationOutcome:
        return self._run(record, root, verify)

    def _finish(
        self, record: IntegrationRecord, status: str, *, result_sha: str | None = None,
        error: str | None = None, retained: Path | None = None,
    ) -> IntegrationOutcome:
        outcome = IntegrationOutcome(
            record.id, status, result_sha=result_sha, error=error,
            retained_worktree=str(retained) if retained else None,
        )
        self.coordinator.finish_integration(record.id, outcome, max_attempts=self.max_attempts)
        return outcome

    def _run(
        self, record: IntegrationRecord, root: Path | None, verify: str | None
    ) -> IntegrationOutcome:
        lease = self.coordinator.current_lease(record.task_id)
        if lease is None or lease.run_id != record.run_id or lease.generation != record.lease_generation:
            return self._finish(record, "superseded", error="lease superseded by a newer owner")
        assert root is not None and verify is not None  # only the superseded path may omit them
        worktree, observed = prepare_integration_worktree(root, record.target_ref)
        merged = _git(worktree, "merge", "--no-ff", "--no-edit", record.candidate_sha)
        if merged.returncode != 0:
            _git(worktree, "merge", "--abort")
            return self._finish(record, "conflict", error=merged.stderr.strip() or "merge conflict", retained=worktree)
        verdict = run_verify(verify, worktree)
        if not verdict.passed:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(record, "failed", error=f"integration verify: {verdict.status}", retained=worktree)
        result_sha = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        updated = _git(root, "update-ref", record.target_ref, result_sha, observed)
        if updated.returncode != 0:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(
                record, "conflict",
                error=updated.stderr.strip() or "target advanced; integration superseded", retained=worktree,
            )
        return self._finish(record, "complete", result_sha=result_sha)
