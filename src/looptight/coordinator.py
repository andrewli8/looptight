"""Repository-private process coordination backed by SQLite."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .claims import MARKER_NAME, has_live_claim
from .fsutil import atomic_write_text

SCHEMA_VERSION = 4

_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'complete', 'failed', 'abandoned')),
    pid INTEGER NOT NULL,
    heartbeat REAL NOT NULL,
    owner TEXT  -- per-worktree identity (claims.owner_id); NULL when unknown
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)
);
CREATE TABLE IF NOT EXISTS leases (
    task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation > 0),
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('proposed', 'accepted', 'rejected')),
    UNIQUE (run_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS integrations (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    lease_generation INTEGER NOT NULL,
    target_ref TEXT NOT NULL,
    observed_sha TEXT,
    candidate_sha TEXT NOT NULL,
    result_sha TEXT,
    state TEXT NOT NULL CHECK (
        state IN ('queued', 'integrating', 'committed', 'complete', 'conflict', 'failed', 'superseded')
    ),
    error TEXT,
    retained_worktree TEXT
);
CREATE TABLE IF NOT EXISTS publications (
    id TEXT PRIMARY KEY,
    integration_id TEXT NOT NULL REFERENCES integrations(id),
    remote TEXT NOT NULL,
    remote_ref TEXT NOT NULL,
    -- observed_local_sha and reconciliation_sha are reserved for a future push-reconciliation
    -- feature (rebase a non-ff-rejected result onto the new remote tip and retry); they are not
    -- yet read or written. Kept rather than dropped so the v4 schema stays unambiguous across DBs.
    observed_local_sha TEXT,
    observed_remote_sha TEXT,
    result_sha TEXT NOT NULL,
    reconciliation_sha TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'publishing', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error TEXT
);
CREATE TABLE IF NOT EXISTS experience (
    id INTEGER PRIMARY KEY,
    idea_id TEXT NOT NULL,
    category TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('failed')),
    created_at REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS experience_idea ON experience(idea_id);
PRAGMA user_version = 4;
COMMIT;
"""

# Migrations are applied in sequence from the database's current version up to
# SCHEMA_VERSION, so a database two versions behind upgrades in a single open.
_MIGRATE_1_TO_2 = """BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS experience (
    id INTEGER PRIMARY KEY,
    idea_id TEXT NOT NULL,
    category TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('failed')),
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS experience_idea ON experience(idea_id);
PRAGMA user_version = 2;
COMMIT;"""

_MIGRATE_2_TO_3 = """BEGIN IMMEDIATE;
ALTER TABLE experience ADD COLUMN reason TEXT NOT NULL DEFAULT '';
PRAGMA user_version = 3;
COMMIT;"""

def _migrate_3_to_4(connection: sqlite3.Connection) -> None:
    """v3→v4: add ``runs.owner`` so the claim sweep can spare a *different* worktree's
    live lease. Guarded — ``ALTER`` only runs when ``runs`` exists and lacks the column.
    A real DB always has ``runs`` (it predates v1); the guard keeps the migration safe
    on a partial DB or a re-applied upgrade rather than crashing the open."""
    connection.execute("BEGIN IMMEDIATE")
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
    ).fetchone()
    if table is not None:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        if "owner" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN owner TEXT")
    connection.execute("PRAGMA user_version = 4")
    connection.execute("COMMIT")

_INIT_RETRY_ATTEMPTS = 50
_INIT_RETRY_SLEEP_S = 0.1


def _initialize_schema(connection: sqlite3.Connection) -> None:
    """Enable WAL and create the schema, tolerating concurrent first-open races.

    SQLite returns SQLITE_BUSY *immediately* for a journal-mode switch (and for the
    schema's immediate transaction) when another process is initializing the same
    fresh database, regardless of ``busy_timeout`` — so retry briefly until one
    writer wins and the rest observe the finished schema.
    """
    last: sqlite3.OperationalError | None = None
    for _ in range(_INIT_RETRY_ATTEMPTS):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(_SCHEMA)
                return
            if version == 1:
                connection.executescript(_MIGRATE_1_TO_2)
                version = 2
            if version == 2:
                connection.executescript(_MIGRATE_2_TO_3)
                version = 3
            if version == 3:
                _migrate_3_to_4(connection)
                version = 4
            if version != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported coordinator schema {version}; expected {SCHEMA_VERSION}"
                )
            return
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            last = exc
            time.sleep(_INIT_RETRY_SLEEP_S)
    raise last if last is not None else sqlite3.OperationalError("coordinator init failed")


@dataclass(frozen=True)
class Run:
    id: str
    kind: str


class CoordinationError(Exception):
    """Raised when a coordinator state transition is invalid (e.g. a stale lease)."""


class CoordinatorUnavailable(Exception):
    """Raised when the coordinator database cannot be opened (corrupt or newer-schema).

    Carries an actionable, user-facing message. The CLI top level renders it as a clean
    error with exit 2 instead of letting a raw ``sqlite3.Error``/``RuntimeError`` traceback
    escape and recur on every invocation.
    """


def _unavailable_message(path: Path, exc: Exception) -> str:
    if isinstance(exc, RuntimeError) and "unsupported coordinator schema" in str(exc):
        return (
            f"{exc}. The coordinator database at {path} was written by a newer looptight; "
            "upgrade looptight, or delete that file to start fresh."
        )
    return (
        f"the coordinator database at {path} is unreadable ({exc}); "
        "delete that file to let looptight recreate it."
    )


class MigrationBlocked(Exception):
    """Raised when activation cannot proceed because live legacy claims exist."""


@dataclass(frozen=True)
class Lease:
    task_id: str
    run_id: str
    generation: int
    payload: dict[str, object]
    _row_id: int


@dataclass(frozen=True)
class IntegrationRecord:
    id: str
    run_id: str
    task_id: int
    lease_generation: int
    target_ref: str
    candidate_sha: str
    state: str
    observed_sha: str | None = None
    result_sha: str | None = None


@dataclass(frozen=True)
class IntegrationOutcome:
    id: str
    status: str  # complete | conflict | failed | superseded
    result_sha: str | None = None
    error: str | None = None
    retained_worktree: str | None = None


@dataclass(frozen=True)
class PublicationRecord:
    id: str
    integration_id: str
    remote: str
    remote_ref: str
    result_sha: str
    state: str


@dataclass(frozen=True)
class PublicationOutcome:
    id: str
    status: str  # complete | failed
    error: str | None = None


def _publication_record(row: tuple[object, ...]) -> PublicationRecord:
    return PublicationRecord(
        id=str(row[0]),
        integration_id=str(row[1]),
        remote=str(row[2]),
        remote_ref=str(row[3]),
        result_sha=str(row[4]),
        state=str(row[5]),
    )


_INTEGRATION_COLUMNS = (
    "id, run_id, task_id, lease_generation, target_ref, candidate_sha, state, "
    "observed_sha, result_sha"
)


def _integration_record(row: tuple[object, ...]) -> IntegrationRecord:
    return IntegrationRecord(
        id=str(row[0]),
        run_id=str(row[1]),
        task_id=int(row[2]),  # type: ignore[arg-type]
        lease_generation=int(row[3]),  # type: ignore[arg-type]
        target_ref=str(row[4]),
        candidate_sha=str(row[5]),
        state=str(row[6]),
        observed_sha=str(row[7]) if row[7] is not None else None,
        result_sha=str(row[8]) if row[8] is not None else None,
    )


def current_run_id() -> str:
    """Return an explicit host-session identity or a fresh invocation identity."""
    return (
        os.environ.get("LOOPTIGHT_RUN_ID")
        or os.environ.get("LOOPTIGHT_SESSION_ID")
        or uuid.uuid4().hex
    )


def coordinator_path(workdir: Path) -> Path | None:
    """Return the repository-private coordinator path, or ``None`` outside Git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=workdir,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = workdir / common
    return common.resolve() / "looptight" / "coordinator.db"


def coordination_scope(workdir: Path) -> str:
    """Where task coordination is shared, as one of ``coordinator`` (SQLite
    coordinator activated), ``file-claims`` (Git repo, legacy file claims), or
    ``none`` (outside Git). Coordination is local to one machine and filesystem;
    cross-machine and network-filesystem coordination are not supported.
    """
    path = coordinator_path(workdir)
    if path is None:
        return "none"
    return "coordinator" if (path.parent / MARKER_NAME).is_file() else "file-claims"


@dataclass
class Coordinator:
    """One connection to a repository's process-safe coordination database."""

    path: Path
    connection: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Path, *, activate: bool = False) -> "Coordinator | None":
        path = coordinator_path(workdir)
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            _initialize_schema(connection)
        except (sqlite3.Error, RuntimeError) as exc:
            # A corrupt/truncated DB raises sqlite3.DatabaseError; a future schema raises
            # RuntimeError. Both are unusable external state — convert to a clean, actionable
            # error rather than letting a traceback escape and recur on every command.
            connection.close()
            raise CoordinatorUnavailable(_unavailable_message(path, exc)) from exc
        except BaseException:
            connection.close()
            raise
        coordinator = cls(path, connection)
        if activate:
            try:
                coordinator.activate_from_legacy()
            except BaseException:
                connection.close()
                raise
        return coordinator

    def activate_from_legacy(self) -> None:
        """Migrate this repository from legacy file claims, failing closed after.

        Refuses while any legacy claim is still live, then writes the
        ``coordinator-format.json`` marker last so legacy claims fail closed and
        the coordinator owns task ownership from here on. Idempotent once written.
        """
        base = self.path.parent
        marker = base / MARKER_NAME
        if marker.exists():
            return
        if has_live_claim(base / "claims"):
            raise MigrationBlocked(
                "live legacy claims exist; finish or let them expire first"
            )
        atomic_write_text(
            marker, json.dumps({"schema_version": SCHEMA_VERSION}, sort_keys=True)
        )

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def start_run(
        self,
        kind: str,
        *,
        now: float | None = None,
        run_id: str | None = None,
        owner: str | None = None,
    ) -> Run:
        identity = run_id or uuid.uuid4().hex
        timestamp = time.time() if now is None else now
        self.connection.execute(
            "INSERT OR IGNORE INTO runs(id, kind, state, pid, heartbeat, owner) "
            "VALUES (?, ?, 'active', ?, ?, ?)",
            (identity, kind, 0, timestamp, owner),
        )
        return Run(identity, kind)

    def claim(
        self,
        tasks: list[dict[str, object]],
        run_id: str,
        *,
        ttl_s: float,
        now: float | None = None,
        owner: str | None = None,
    ) -> Lease | None:
        timestamp = time.time() if now is None else now
        fingerprints = [str(task["id"]) for task in tasks]
        payloads = {str(task["id"]): task for task in tasks}
        with self.transaction(immediate=True):
            for fingerprint, payload in payloads.items():
                self.connection.execute(
                    """INSERT INTO tasks(fingerprint, payload, state)
                       VALUES (?, ?, 'queued')
                       ON CONFLICT(fingerprint) DO UPDATE SET payload=excluded.payload""",
                    (fingerprint, json.dumps(payload, sort_keys=True)),
                )

            if fingerprints:
                marks = ",".join("?" for _ in fingerprints)
                stale_rows = self.connection.execute(
                    f"SELECT id FROM tasks WHERE fingerprint NOT IN ({marks})",
                    fingerprints,
                ).fetchall()
            else:
                stale_rows = self.connection.execute("SELECT id FROM tasks").fetchall()
            for (row_id,) in stale_rows:
                # The DB is shared across a repo's worktrees, which at different
                # commits/branches see divergent candidate sets. A task absent from
                # THIS caller's set but holding a live lease owned by a DIFFERENT
                # worktree is that worktree's in-flight work, not abandoned — leave it
                # alone. Same-owner reconcile (a task removed from one worktree's own
                # set) and owner-less runs still retire. Spare only when both owners
                # are known and differ, so the guard never fires without full info.
                if owner is not None:
                    peer = self.connection.execute(
                        """SELECT 1 FROM leases l JOIN runs r ON r.id = l.run_id
                           WHERE l.task_id = ? AND l.expires_at > ?
                             AND r.owner IS NOT NULL AND r.owner <> ?""",
                        (row_id, timestamp, owner),
                    ).fetchone()
                    if peer is not None:
                        continue
                self.connection.execute("DELETE FROM leases WHERE task_id = ?", (row_id,))
                self.connection.execute(
                    "UPDATE tasks SET state = 'complete' WHERE id = ?", (row_id,)
                )

            expired = self.connection.execute(
                "SELECT task_id FROM leases WHERE expires_at <= ?", (timestamp,)
            ).fetchall()
            for (row_id,) in expired:
                self.connection.execute("DELETE FROM leases WHERE task_id = ?", (row_id,))
                self.connection.execute(
                    "UPDATE tasks SET state = 'queued' WHERE id = ?", (row_id,)
                )

            if not fingerprints:
                return None
            marks = ",".join("?" for _ in fingerprints)
            owned = self.connection.execute(
                f"""SELECT t.id, t.fingerprint, t.payload, l.generation
                    FROM leases l JOIN tasks t ON t.id = l.task_id
                    WHERE l.run_id = ? AND t.fingerprint IN ({marks})
                    ORDER BY t.id LIMIT 1""",
                (run_id, *fingerprints),
            ).fetchone()
            if owned is not None:
                return self._lease(owned, run_id)

            selected = self.connection.execute(
                f"""SELECT t.id, t.fingerprint, t.payload
                    FROM tasks t LEFT JOIN leases l ON l.task_id = t.id
                    WHERE t.fingerprint IN ({marks}) AND t.state = 'queued'
                      AND l.task_id IS NULL
                    ORDER BY t.id LIMIT 1""",
                fingerprints,
            ).fetchone()
            if selected is None:
                return None
            row_id, fingerprint, payload = selected
            self.connection.execute(
                "UPDATE tasks SET state = 'leased', attempts = attempts + 1 WHERE id = ?",
                (row_id,),
            )
            generation = self.connection.execute(
                "SELECT attempts FROM tasks WHERE id = ?", (row_id,)
            ).fetchone()[0]
            self.connection.execute(
                "INSERT INTO leases(task_id, run_id, generation, expires_at) VALUES (?, ?, ?, ?)",
                (row_id, run_id, generation, timestamp + ttl_s),
            )
            return Lease(fingerprint, run_id, generation, json.loads(payload), row_id)

    @staticmethod
    def _lease(row: tuple[object, ...], run_id: str) -> Lease:
        row_id, fingerprint, payload, generation = row
        return Lease(str(fingerprint), run_id, int(generation), json.loads(str(payload)), int(row_id))

    def renew(self, lease: Lease, *, ttl_s: float, now: float | None = None) -> bool:
        timestamp = time.time() if now is None else now
        with self.transaction(immediate=True):
            changed = self.connection.execute(
                """UPDATE leases SET expires_at = ?
                   WHERE task_id = ? AND run_id = ? AND generation = ? AND expires_at > ?""",
                (timestamp + ttl_s, lease._row_id, lease.run_id, lease.generation, timestamp),
            )
            return changed.rowcount == 1

    def complete(self, lease: Lease) -> bool:
        with self.transaction(immediate=True):
            current = self.connection.execute(
                "SELECT 1 FROM leases WHERE task_id = ? AND run_id = ? AND generation = ?",
                (lease._row_id, lease.run_id, lease.generation),
            ).fetchone()
            if current is None:
                return False
            self.connection.execute("DELETE FROM leases WHERE task_id = ?", (lease._row_id,))
            self.connection.execute(
                "UPDATE tasks SET state = 'complete' WHERE id = ?", (lease._row_id,)
            )
            return True

    def heartbeat(self, run_id: str, *, now: float | None = None) -> None:
        """Refresh an active run's heartbeat so it is not reaped as abandoned."""
        timestamp = time.time() if now is None else now
        with self.transaction(immediate=True):
            self.connection.execute(
                "UPDATE runs SET heartbeat = ? WHERE id = ? AND state = 'active'",
                (timestamp, run_id),
            )

    def reap_abandoned(self, *, older_than_s: float, now: float | None = None) -> tuple[str, ...]:
        """Abandon active runs whose heartbeat predates the deadline and free their leases.

        A dead session's lease would otherwise linger until its TTL; reaping marks the
        run ``abandoned`` and requeues its leased tasks. Returns the reaped run IDs.
        """
        timestamp = time.time() if now is None else now
        cutoff = timestamp - older_than_s
        with self.transaction(immediate=True):
            stale = self.connection.execute(
                "SELECT id FROM runs WHERE state = 'active' AND heartbeat < ?", (cutoff,)
            ).fetchall()
            for (run_id,) in stale:
                leased = self.connection.execute(
                    "SELECT task_id FROM leases WHERE run_id = ?", (run_id,)
                ).fetchall()
                for (task_id,) in leased:
                    self.connection.execute("DELETE FROM leases WHERE task_id = ?", (task_id,))
                    self.connection.execute(
                        "UPDATE tasks SET state = 'queued' WHERE id = ? AND state = 'leased'",
                        (task_id,),
                    )
                self.connection.execute(
                    "UPDATE runs SET state = 'abandoned' WHERE id = ?", (run_id,)
                )
            return tuple(str(row[0]) for row in stale)

    def summary(
        self, run_id: str | None = None, *, now: float | None = None
    ) -> tuple[str | None, int]:
        timestamp = time.time() if now is None else now
        active = self.connection.execute(
            "SELECT COUNT(*) FROM leases WHERE expires_at > ?", (timestamp,)
        ).fetchone()[0]
        owned: str | None = None
        if run_id:
            row = self.connection.execute(
                """SELECT t.fingerprint FROM leases l JOIN tasks t ON t.id = l.task_id
                   WHERE l.run_id = ? AND l.expires_at > ? ORDER BY t.id LIMIT 1""",
                (run_id, timestamp),
            ).fetchone()
            owned = str(row[0]) if row else None
        return owned, int(active)

    def active_lease_for_owner(self, owner: str, *, now: float | None = None) -> Lease | None:
        """The live lease (with task payload) currently held by ``owner``, if any.

        Owner-keyed (via ``runs.owner``), not run-keyed, so a Stop hook can find the task this
        worktree's session claimed without sharing the session's run id.
        """
        timestamp = time.time() if now is None else now
        row = self.connection.execute(
            """SELECT t.id, t.fingerprint, l.run_id, l.generation, t.payload
               FROM leases l JOIN tasks t ON t.id = l.task_id JOIN runs r ON r.id = l.run_id
               WHERE r.owner = ? AND l.expires_at > ? ORDER BY t.id LIMIT 1""",
            (owner, timestamp),
        ).fetchone()
        if row is None:
            return None
        task_id, fingerprint, run_id, generation, payload = row
        return Lease(
            str(fingerprint), str(run_id), int(generation), json.loads(payload), int(task_id)
        )

    def current_lease(self, task_id: int) -> Lease | None:
        row = self.connection.execute(
            """SELECT t.fingerprint, l.run_id, l.generation, t.payload
               FROM leases l JOIN tasks t ON t.id = l.task_id WHERE l.task_id = ?""",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        fingerprint, run_id, generation, payload = row
        return Lease(str(fingerprint), str(run_id), int(generation), json.loads(payload), int(task_id))

    def lease_for(self, fingerprint: str, run_id: str) -> Lease | None:
        """Return the lease ``run_id`` holds for ``fingerprint``, if any."""
        row = self.connection.execute(
            """SELECT t.id, l.generation, t.payload
               FROM leases l JOIN tasks t ON t.id = l.task_id
               WHERE t.fingerprint = ? AND l.run_id = ?""",
            (fingerprint, run_id),
        ).fetchone()
        if row is None:
            return None
        task_id, generation, payload = row
        return Lease(str(fingerprint), str(run_id), int(generation), json.loads(payload), int(task_id))

    def enqueue_integration(self, lease: Lease, target_ref: str, candidate_sha: str) -> str:
        """Queue a verified worker branch for integration; fenced to the live lease."""
        with self.transaction(immediate=True):
            active = self.connection.execute(
                "SELECT 1 FROM leases WHERE task_id = ? AND run_id = ? AND generation = ?",
                (lease._row_id, lease.run_id, lease.generation),
            ).fetchone()
            if active is None:
                raise CoordinationError("cannot enqueue integration for a stale or released lease")
            integration_id = uuid.uuid4().hex
            self.connection.execute(
                """INSERT INTO integrations(
                       id, run_id, task_id, lease_generation, target_ref, candidate_sha, state)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued')""",
                (integration_id, lease.run_id, lease._row_id, lease.generation, target_ref, candidate_sha),
            )
            return integration_id

    def integration(self, integration_id: str) -> IntegrationRecord | None:
        row = self.connection.execute(
            f"SELECT {_INTEGRATION_COLUMNS} FROM integrations WHERE id = ?",
            (integration_id,),
        ).fetchone()
        return _integration_record(row) if row else None

    def next_queued_integration(self) -> IntegrationRecord | None:
        """Return the oldest queued integration (global FIFO by insertion sequence)."""
        row = self.connection.execute(
            f"SELECT {_INTEGRATION_COLUMNS} FROM integrations WHERE state = 'queued' "
            "ORDER BY sequence LIMIT 1"
        ).fetchone()
        return _integration_record(row) if row else None

    def integrating_records(self) -> tuple[IntegrationRecord, ...]:
        """Return non-terminal integrations left mid-flight (for crash recovery).

        Includes ``committed`` records (commit done, ref not yet advanced) so reconcile can
        finish them from the durable ``result_sha`` rather than the volatile worktree.
        """
        rows = self.connection.execute(
            f"SELECT {_INTEGRATION_COLUMNS} FROM integrations "
            "WHERE state IN ('integrating', 'committed') ORDER BY sequence"
        ).fetchall()
        return tuple(_integration_record(row) for row in rows)

    def begin_integration(self, integration_id: str, observed_sha: str) -> None:
        """Record the observed target tip and mark the integration in-flight."""
        with self.transaction(immediate=True):
            self.connection.execute(
                "UPDATE integrations SET state = 'integrating', observed_sha = ? WHERE id = ?",
                (observed_sha, integration_id),
            )

    def mark_integration_committed(self, integration_id: str, result_sha: str) -> None:
        """Durably record the merge commit before advancing the target ref.

        Persisting ``result_sha`` + state ``committed`` makes crash recovery independent of the
        shared per-target-ref worktree, which a later integration may reset before reconcile runs.
        """
        with self.transaction(immediate=True):
            self.connection.execute(
                "UPDATE integrations SET state = 'committed', result_sha = ? WHERE id = ?",
                (result_sha, integration_id),
            )

    def finish_integration(
        self, integration_id: str, outcome: IntegrationOutcome, *, max_attempts: int = 3
    ) -> None:
        """Apply a terminal integration outcome atomically.

        complete  → integration complete, task complete, fenced lease deleted.
        superseded→ integration superseded; the (newer) owner's lease is untouched.
        conflict/failed → integration recorded with retained worktree, fenced lease
                    released, and the task requeued below the attempt cap or failed.
        """
        with self.transaction(immediate=True):
            row = self.connection.execute(
                "SELECT task_id, lease_generation FROM integrations WHERE id = ?",
                (integration_id,),
            ).fetchone()
            if row is None:
                return
            task_id, generation = int(row[0]), int(row[1])
            if outcome.status == "complete":
                self.connection.execute(
                    "UPDATE integrations SET state = 'complete', result_sha = ?, error = NULL WHERE id = ?",
                    (outcome.result_sha, integration_id),
                )
                self.connection.execute(
                    "DELETE FROM leases WHERE task_id = ? AND generation = ?", (task_id, generation)
                )
                self.connection.execute(
                    "UPDATE tasks SET state = 'complete' WHERE id = ?", (task_id,)
                )
            elif outcome.status == "superseded":
                self.connection.execute(
                    "UPDATE integrations SET state = 'superseded', error = ? WHERE id = ?",
                    (outcome.error, integration_id),
                )
            else:  # conflict / failed
                self.connection.execute(
                    "UPDATE integrations SET state = ?, error = ?, retained_worktree = ? WHERE id = ?",
                    (outcome.status, outcome.error, outcome.retained_worktree, integration_id),
                )
                self.connection.execute(
                    "DELETE FROM leases WHERE task_id = ? AND generation = ?", (task_id, generation)
                )
                attempts_row = self.connection.execute(
                    "SELECT attempts FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                attempts = int(attempts_row[0]) if attempts_row else 0
                self.connection.execute(
                    "UPDATE tasks SET state = ? WHERE id = ?",
                    ("queued" if attempts < max_attempts else "failed", task_id),
                )

    def enqueue_publication(self, integration_id: str, remote: str, remote_ref: str) -> str:
        """Queue a completed integration's result for publication to ``remote``."""
        with self.transaction(immediate=True):
            row = self.connection.execute(
                "SELECT result_sha, state FROM integrations WHERE id = ?", (integration_id,)
            ).fetchone()
            if row is None or row[1] != "complete" or not row[0]:
                raise CoordinationError("integration must be complete before publication")
            publication_id = uuid.uuid4().hex
            self.connection.execute(
                """INSERT INTO publications(id, integration_id, remote, remote_ref, result_sha, state)
                   VALUES (?, ?, ?, ?, ?, 'queued')""",
                (publication_id, integration_id, remote, remote_ref, row[0]),
            )
            return publication_id

    def publication(self, publication_id: str) -> PublicationRecord | None:
        row = self.connection.execute(
            """SELECT id, integration_id, remote, remote_ref, result_sha, state
               FROM publications WHERE id = ?""",
            (publication_id,),
        ).fetchone()
        return _publication_record(row) if row else None

    def next_pending_publication(self) -> PublicationRecord | None:
        """Oldest publication not yet finalized (queued or interrupted mid-publish)."""
        row = self.connection.execute(
            """SELECT id, integration_id, remote, remote_ref, result_sha, state
               FROM publications WHERE state IN ('queued', 'publishing') ORDER BY rowid LIMIT 1"""
        ).fetchone()
        return _publication_record(row) if row else None

    def begin_publication(self, publication_id: str, observed_remote_sha: str | None) -> None:
        with self.transaction(immediate=True):
            self.connection.execute(
                "UPDATE publications SET state = 'publishing', observed_remote_sha = ? WHERE id = ?",
                (observed_remote_sha, publication_id),
            )

    def finish_publication(self, publication_id: str, outcome: PublicationOutcome) -> None:
        with self.transaction(immediate=True):
            if outcome.status == "complete":
                self.connection.execute(
                    "UPDATE publications SET state = 'complete', error = NULL WHERE id = ?",
                    (publication_id,),
                )
            else:
                self.connection.execute(
                    "UPDATE publications SET state = 'failed', attempts = attempts + 1, error = ? WHERE id = ?",
                    (outcome.error, publication_id),
                )

    def submit_proposals(
        self, run_id: str, candidates: list[dict[str, object]], generation: str
    ) -> tuple[str, ...]:
        """Record a planner's grounded proposals and dedupe equivalent tasks.

        Concurrent planners that propose overlapping work converge to one task per
        fingerprint via the uniqueness constraints, under a single immediate
        transaction. ``generation`` tags the proposing run's plan revision.
        """
        accepted: list[str] = []
        with self.transaction(immediate=True):
            for candidate in candidates:
                fingerprint = str(candidate["id"])
                payload = json.dumps(candidate, sort_keys=True)
                self.connection.execute(
                    """INSERT OR IGNORE INTO proposals(run_id, fingerprint, payload, state)
                       VALUES (?, ?, ?, 'proposed')""",
                    (run_id, fingerprint, payload),
                )
                self.connection.execute(
                    """INSERT INTO tasks(fingerprint, payload, state) VALUES (?, ?, 'queued')
                       ON CONFLICT(fingerprint) DO NOTHING""",
                    (fingerprint, payload),
                )
                accepted.append(fingerprint)
        return tuple(accepted)

    def status(self, run_id: str | None = None, *, now: float | None = None) -> dict[str, object]:
        """Coordinator counts for additive projection into ``status`` output."""
        claimed_task, active_claims = self.summary(run_id, now=now)
        counts = {
            "queued_tasks": "SELECT COUNT(*) FROM tasks WHERE state = 'queued'",
            "queued_integrations": "SELECT COUNT(*) FROM integrations WHERE state = 'queued'",
            "pending_publications": (
                "SELECT COUNT(*) FROM publications WHERE state IN ('queued', 'publishing')"
            ),
        }
        projected = {key: int(self.connection.execute(sql).fetchone()[0]) for key, sql in counts.items()}
        return {"claimed_task": claimed_task, "active_claims": active_claims, **projected}

    def record_failure(
        self, idea_id: str, category: str, *, reason: str = "", now: float | None = None
    ) -> None:
        """Record one local 'failed' outcome for an idea, with an optional reason
        (e.g. 'conflict', 'fail', 'timeout'). Never pushed."""
        timestamp = time.time() if now is None else now
        with self.transaction(immediate=True):
            self.connection.execute(
                "INSERT INTO experience(idea_id, category, outcome, created_at, reason) "
                "VALUES (?, ?, 'failed', ?, ?)",
                (idea_id, category, timestamp, reason),
            )

    def failure_reasons(self) -> dict[str, str]:
        """Dominant (most frequent) non-empty failure reason per category, so the
        planner note can say *why* a source tends to fail, not just that it does."""
        rows = self.connection.execute(
            "SELECT category, reason, COUNT(*) FROM experience "
            "WHERE outcome = 'failed' AND reason != '' GROUP BY category, reason"
        ).fetchall()
        best: dict[str, tuple[int, str]] = {}
        for category, reason, count in rows:
            n = int(count)
            current = best.get(str(category))
            if current is None or n > current[0]:
                best[str(category)] = (n, str(reason))
        return {category: reason for category, (_n, reason) in best.items()}

    def recent_failures(self, *, window_s: float, now: float | None = None) -> dict[str, int]:
        """Failure counts per idea within window_s, counting only in-window failures."""
        timestamp = time.time() if now is None else now
        cutoff = timestamp - window_s
        rows = self.connection.execute(
            """SELECT idea_id, COUNT(*) FROM experience
               WHERE outcome = 'failed' AND created_at >= :cutoff
               GROUP BY idea_id""",
            {"cutoff": cutoff},
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def failure_counts(self) -> dict[str, int]:
        """Total failures per category (for yield statistics)."""
        rows = self.connection.execute(
            "SELECT category, COUNT(*) FROM experience WHERE outcome = 'failed' GROUP BY category"
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def close(self) -> None:
        self.connection.close()
