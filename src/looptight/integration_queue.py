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

from .coordinator import (
    Coordinator,
    IntegrationOutcome,
    IntegrationRecord,
    PublicationOutcome,
    PublicationRecord,
)
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


# A deterministic committer identity for looptight's automated commits, so merges
# and integrations succeed even where no ambient git identity is configured (CI,
# fresh containers). Read-only git commands ignore it.
_GIT_IDENTITY = ("-c", "user.name=looptight", "-c", "user.email=looptight@localhost")


def _git_env() -> dict[str, str]:
    """Environment for git subprocesses: non-interactive so a network op (push,
    fetch) can never block on a credential prompt in a headless run — the daemon's
    whole purpose is unattended operation. Credential helpers still work; only the
    interactive terminal-prompt fallback is disabled, turning a would-be hang into a
    fast failure the queue can report and retry."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *_GIT_IDENTITY, *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            env=_git_env(),
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


_TRAILER_KEY = "Looptight-Integration-ID"


def _trailer_commit_on_ref(root: Path, ref: str, integration_id: str) -> str | None:
    """The newest commit reachable from ``ref`` carrying this integration's trailer."""
    result = _git(root, "log", ref, "-1", "--pretty=%H", f"--grep={_TRAILER_KEY}: {integration_id}")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _committed_result_in_worktree(worktree: Path, integration_id: str) -> str | None:
    """The integration worktree's HEAD if it already carries this integration's trailer."""
    head = _git(worktree, "rev-parse", "HEAD")
    if head.returncode != 0:
        return None
    body = _git(worktree, "log", "-1", "--pretty=%B")
    if f"{_TRAILER_KEY}: {integration_id}" in body.stdout:
        return head.stdout.strip()
    return None


class InjectedCrash(Exception):
    """Test-only crash injected at a named integration boundary."""


class Integrator:
    """Drain queued integrations one at a time, under the repository lock.

    Each record is fenced to its lease generation: a record whose lease has since
    been reassigned is ``superseded`` (the new owner keeps its lease). Otherwise the
    candidate is merged into a coordinator-owned worktree, verified, committed with a
    ``Looptight-Integration-ID`` trailer, and the target ref advanced with a
    compare-and-swap. The trailer makes the result idempotently recoverable:
    :meth:`reconcile` resolves any integration left mid-flight by a crash to exactly
    one reachable result.
    """

    def __init__(
        self, coordinator: Coordinator, *, lock_timeout_s: float = 300.0,
        max_attempts: int = 3, crash_after: str | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.lock_timeout_s = lock_timeout_s
        self.max_attempts = max_attempts
        self.crash_after = crash_after

    def _maybe_crash(self, boundary: str) -> None:
        if self.crash_after == boundary:
            raise InjectedCrash(boundary)

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

    def reconcile(self, root: Path, verify: str) -> tuple[IntegrationOutcome, ...]:
        """Resolve every integration left ``integrating`` by a crash, idempotently."""
        outcomes: list[IntegrationOutcome] = []
        with IntegrationLock.acquire(git_common_dir(root), self.lock_timeout_s):
            for record in self.coordinator.integrating_records():
                outcomes.append(self._reconcile_one(record, root, verify))
        return tuple(outcomes)

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

    @staticmethod
    def _superseded(record: IntegrationRecord, lease) -> bool:
        """True when ``record``'s lease has been reassigned (reaped + reclaimed by a newer
        owner/generation, or gone). Such a record must never commit — on the live path or
        the crash-reconcile re-apply path."""
        return (
            lease is None
            or lease.run_id != record.run_id
            or lease.generation != record.lease_generation
        )

    def _run(
        self, record: IntegrationRecord, root: Path | None, verify: str | None
    ) -> IntegrationOutcome:
        lease = self.coordinator.current_lease(record.task_id)
        if self._superseded(record, lease):
            return self._finish(record, "superseded", error="lease superseded by a newer owner")
        if root is None or verify is None:  # only the superseded path may omit them
            raise ValueError("root and verify are required to integrate a non-superseded record")
        idea = str(lease.payload.get("idea_id") or "")
        category = str(lease.payload.get("source") or "")
        worktree, observed = prepare_integration_worktree(root, record.target_ref)
        self.coordinator.begin_integration(record.id, observed)
        return self._apply(record, root, verify, worktree, observed, idea, category)

    def _apply(
        self, record: IntegrationRecord, root: Path, verify: str, worktree: Path, observed: str,
        idea: str = "", category: str = "",
    ) -> IntegrationOutcome:
        merged = _git(worktree, "merge", "--no-commit", "--no-ff", record.candidate_sha)
        if merged.returncode != 0:
            _git(worktree, "merge", "--abort")
            if idea:
                try:
                    self.coordinator.record_failure(idea, category, reason="conflict")
                except Exception:
                    pass  # advisory signal; never let it break a clean integration failure
            return self._finish(record, "conflict", error=merged.stderr.strip() or "merge conflict", retained=worktree)
        verdict = run_verify(verify, worktree)
        if not verdict.passed:
            _git(worktree, "reset", "--hard", observed)
            if idea:
                try:
                    self.coordinator.record_failure(idea, category, reason=verdict.status)
                except Exception:
                    pass  # advisory signal; never let it break a clean integration failure
            return self._finish(record, "failed", error=f"integration verify: {verdict.status}", retained=worktree)
        self._maybe_crash("after_merge")
        # Record the task source too (`<idea> landed <source>`), so the self-model
        # can credit the category that produced a landed change, not only the idea.
        outcome_value = f"{idea} landed {category}".strip() if idea else ""
        outcome_trailer = f"\nLooptight-Outcome: {outcome_value}" if outcome_value else ""
        message = (
            f"merge: looptight integration {record.id}\n\n"
            f"{_TRAILER_KEY}: {record.id}{outcome_trailer}"
        )
        committed = _git(worktree, "commit", "-m", message)
        if committed.returncode != 0:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(record, "failed", error=committed.stderr.strip() or "integration commit failed", retained=worktree)
        result_sha = _git(worktree, "rev-parse", "HEAD").stdout.strip()
        # Persist the commit durably *before* the ref advance, so a crash here recovers from the
        # recorded result_sha rather than the shared worktree (which a later integration may reset).
        self.coordinator.mark_integration_committed(record.id, result_sha)
        self._maybe_crash("after_commit")
        updated = _git(root, "update-ref", record.target_ref, result_sha, observed)
        if updated.returncode != 0:
            _git(worktree, "reset", "--hard", observed)
            return self._finish(
                record, "conflict",
                error=updated.stderr.strip() or "target advanced; integration superseded", retained=worktree,
            )
        self._maybe_crash("after_update_ref")
        outcome = self._finish(record, "complete", result_sha=result_sha)
        self._maybe_crash("after_db_update")
        return outcome

    def _reconcile_one(
        self, record: IntegrationRecord, root: Path, verify: str
    ) -> IntegrationOutcome:
        # Already reachable from the ref (crashed after update-ref): just finalize.
        on_ref = _trailer_commit_on_ref(root, record.target_ref, record.id)
        if on_ref:
            return self._finish(record, "complete", result_sha=on_ref)
        worktree = integration_worktree(root, record.target_ref)
        observed = record.observed_sha or _git(root, "rev-parse", record.target_ref).stdout.strip()
        # Committed but not yet on the ref (crashed after commit): advance the ref. Prefer the
        # durably-recorded result_sha (state `committed`) so recovery does not depend on the shared
        # worktree, which a later integration may have reset; fall back to the worktree HEAD.
        committed = record.result_sha or (
            _committed_result_in_worktree(worktree, record.id) if worktree.exists() else None
        )
        if committed:
            updated = _git(root, "update-ref", record.target_ref, committed, observed)
            if updated.returncode == 0:
                return self._finish(record, "complete", result_sha=committed)
            on_ref_again = _trailer_commit_on_ref(root, record.target_ref, record.id)
            if on_ref_again:
                return self._finish(record, "complete", result_sha=on_ref_again)
            return self._finish(record, "conflict", error="target advanced during reconcile", retained=worktree)
        # Nothing committed (crashed mid-merge): re-apply from the observed base — but only if
        # this record still owns the lease. A reaped+reclaimed task (newer owner/generation) must
        # not have its stale candidate re-merged and committed here, the same fence `_run` applies.
        lease = self.coordinator.current_lease(record.task_id)
        if self._superseded(record, lease):
            return self._finish(record, "superseded", error="lease superseded by a newer owner")
        idea = str(lease.payload.get("idea_id") or "")
        category = str(lease.payload.get("source") or "")
        fresh_worktree, fresh_observed = prepare_integration_worktree(root, record.target_ref)
        return self._apply(record, root, verify, fresh_worktree, fresh_observed, idea, category)


def _is_ancestor(root: Path, sha: str, tip: str) -> bool:
    """True if ``sha`` is reachable from ``tip`` (the remote already has the result)."""
    if not sha or not tip:
        return False
    return _git(root, "merge-base", "--is-ancestor", sha, tip).returncode == 0


def _default_push(root: Path, remote: str, result_sha: str, remote_ref: str) -> int:
    """Push the exact result SHA to ``remote_ref`` without force or candidate replay."""
    return _git(root, "push", remote, f"{result_sha}:{remote_ref}").returncode


class Publisher:
    """Publish completed integrations to a remote idempotently.

    Before pushing, it fetches the remote ref and finalizes without a second push if
    the result is already present (a crash after a successful push is recovered, not
    duplicated). It pushes only the exact result SHA, never replays the candidate, and
    never force-pushes. ``push`` is injectable for tests.
    """

    def __init__(self, coordinator: Coordinator, *, push=None, lock_timeout_s: float = 300.0) -> None:
        self.coordinator = coordinator
        self._push = push if push is not None else _default_push
        self.lock_timeout_s = lock_timeout_s

    def run_next(self, root: Path) -> PublicationOutcome | None:
        with IntegrationLock.acquire(git_common_dir(root), self.lock_timeout_s):
            record = self.coordinator.next_pending_publication()
            if record is None:
                return None
            return self._publish(record, root)

    def reconcile(self, root: Path) -> tuple[PublicationOutcome, ...]:
        outcomes: list[PublicationOutcome] = []
        while True:
            outcome = self.run_next(root)
            if outcome is None:
                break
            outcomes.append(outcome)
        return tuple(outcomes)

    def _finish(self, record: PublicationRecord, status: str, *, error: str | None = None) -> PublicationOutcome:
        outcome = PublicationOutcome(record.id, status, error=error)
        self.coordinator.finish_publication(record.id, outcome)
        return outcome

    #: Bounded re-fetch+retry of the exact-SHA non-force push, so a transient non-fast-forward
    #: rejection (the remote moved between the fetch and the push) clears itself instead of
    #: stranding an integrated result for manual reconcile.
    _MAX_PUSH_ATTEMPTS = 3

    def _publish(self, record: PublicationRecord, root: Path) -> PublicationOutcome:
        for attempt in range(self._MAX_PUSH_ATTEMPTS):
            _git(root, "fetch", "-q", record.remote, record.remote_ref)
            remote_tip = _git(root, "rev-parse", "--verify", "-q", "FETCH_HEAD").stdout.strip()
            if attempt == 0:
                self.coordinator.begin_publication(record.id, remote_tip or None)
            if _is_ancestor(root, record.result_sha, remote_tip):
                return self._finish(record, "complete")  # remote already has it; no push
            if self._push(root, record.remote, record.result_sha, record.remote_ref) == 0:
                return self._finish(record, "complete")
            # Non-fast-forward rejection: the remote moved. Re-fetch and retry — never force,
            # never replay the candidate, only the exact result SHA — until the bound is reached.
        return self._finish(
            record, "failed", error="push rejected after retries; fetch and reconcile"
        )
