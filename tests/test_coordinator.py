"""Repository-private SQLite coordinator tests."""

from __future__ import annotations

import sqlite3
import subprocess

import pytest

from looptight.coordinator import Coordinator, coordinator_path


def _repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def test_coordinator_is_private_and_isolated_by_repository(tmp_path):
    first = _repo(tmp_path / "first")
    second = _repo(tmp_path / "second")

    one = Coordinator.open(first)
    two = Coordinator.open(second)

    assert one is not None and two is not None
    assert one.path == (first / ".git" / "looptight" / "coordinator.db").resolve()
    assert two.path != one.path
    assert one.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert one.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert one.connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_coordinator_path_is_none_outside_git(tmp_path):
    assert coordinator_path(tmp_path) is None
    assert Coordinator.open(tmp_path) is None


def test_schema_rejects_duplicate_task_fingerprints(tmp_path):
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None

    coordinator.connection.execute(
        "INSERT INTO tasks(fingerprint, payload, state) VALUES (?, ?, ?)",
        ("same", "{}", "queued"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        coordinator.connection.execute(
            "INSERT INTO tasks(fingerprint, payload, state) VALUES (?, ?, ?)",
            ("same", "{}", "queued"),
        )


def test_transaction_rolls_back_on_exception(tmp_path):
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None

    with pytest.raises(RuntimeError):
        with coordinator.transaction(immediate=True):
            coordinator.connection.execute(
                "INSERT INTO tasks(fingerprint, payload, state) VALUES (?, ?, ?)",
                ("rolled-back", "{}", "queued"),
            )
            raise RuntimeError("stop")

    count = coordinator.connection.execute(
        "SELECT COUNT(*) FROM tasks WHERE fingerprint = ?", ("rolled-back",)
    ).fetchone()[0]
    assert count == 0


def test_schema_contains_coordinator_state_tables(tmp_path):
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    tables = {
        row[0]
        for row in coordinator.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"runs", "tasks", "leases", "proposals", "integrations", "publications"} <= tables

