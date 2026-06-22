"""Repository-private process coordination backed by SQLite."""

from __future__ import annotations

import sqlite3
import subprocess
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

    def close(self) -> None:
        self.connection.close()

