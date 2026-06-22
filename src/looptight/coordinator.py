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

SCHEMA_VERSION = 1

_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'complete', 'failed', 'abandoned')),
    pid INTEGER NOT NULL,
    heartbeat REAL NOT NULL
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
    observed_local_sha TEXT,
    observed_remote_sha TEXT,
    result_sha TEXT NOT NULL,
    reconciliation_sha TEXT,
    state TEXT NOT NULL CHECK (state IN ('queued', 'publishing', 'complete', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error TEXT
);
PRAGMA user_version = 1;
COMMIT;
"""


@dataclass(frozen=True)
class Run:
    id: str
    kind: str


class CoordinationError(Exception):
    """Raised when a coordinator state transition is invalid (e.g. a stale lease)."""


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


@dataclass(frozen=True)
class IntegrationOutcome:
    id: str
    status: str  # complete | conflict | failed | superseded
    result_sha: str | None = None
    error: str | None = None
    retained_worktree: str | None = None


def _integration_record(row: tuple[object, ...]) -> IntegrationRecord:
    return IntegrationRecord(
        id=str(row[0]),
        run_id=str(row[1]),
        task_id=int(row[2]),  # type: ignore[arg-type]
        lease_generation=int(row[3]),  # type: ignore[arg-type]
        target_ref=str(row[4]),
        candidate_sha=str(row[5]),
        state=str(row[6]),
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


@dataclass
class Coordinator:
    """One connection to a repository's process-safe coordination database."""

    path: Path
    connection: sqlite3.Connection

    @classmethod
    def open(cls, workdir: Path) -> "Coordinator | None":
        path = coordinator_path(workdir)
        if path is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            connection.executescript(_SCHEMA)
        elif version != SCHEMA_VERSION:
            connection.close()
            raise RuntimeError(
                f"unsupported coordinator schema {version}; expected {SCHEMA_VERSION}"
            )
        return cls(path, connection)

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
        self, kind: str, *, now: float | None = None, run_id: str | None = None
    ) -> Run:
        identity = run_id or uuid.uuid4().hex
        timestamp = time.time() if now is None else now
        self.connection.execute(
            "INSERT OR IGNORE INTO runs(id, kind, state, pid, heartbeat) VALUES (?, ?, 'active', ?, ?)",
            (identity, kind, 0, timestamp),
        )
        return Run(identity, kind)

    def claim(
        self,
        tasks: list[dict[str, object]],
        run_id: str,
        *,
        ttl_s: float,
        now: float | None = None,
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
            """SELECT id, run_id, task_id, lease_generation, target_ref, candidate_sha, state
               FROM integrations WHERE id = ?""",
            (integration_id,),
        ).fetchone()
        return _integration_record(row) if row else None

    def next_queued_integration(self) -> IntegrationRecord | None:
        """Return the oldest queued integration (global FIFO by insertion sequence)."""
        row = self.connection.execute(
            """SELECT id, run_id, task_id, lease_generation, target_ref, candidate_sha, state
               FROM integrations WHERE state = 'queued' ORDER BY sequence LIMIT 1"""
        ).fetchone()
        return _integration_record(row) if row else None

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

    def close(self) -> None:
        self.connection.close()
