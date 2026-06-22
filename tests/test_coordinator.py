"""Repository-private SQLite coordinator tests."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from multiprocessing import get_context

import pytest

from looptight.claims import ClaimStore, LegacyClaimsDisabled, claim_dir
from looptight.coordinator import Coordinator, MigrationBlocked, coordinator_path


def _repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def _claim_once(repo, tasks, output):
    coordinator = Coordinator.open(repo)
    assert coordinator is not None
    run = coordinator.start_run("test")
    lease = coordinator.claim(tasks, run.id, ttl_s=60)
    output.put((run.id, lease.task_id, lease.generation))


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


def test_ten_same_directory_processes_claim_distinct_tasks(tmp_path):
    repo = _repo(tmp_path / "repo")
    coordinator = Coordinator.open(repo)
    assert coordinator is not None
    coordinator.close()  # initialize schema before deliberately concurrent opens
    tasks = [{"id": f"task-{number}", "goal": f"task {number}"} for number in range(10)]
    context = get_context("fork")
    output = context.Queue()
    processes = [context.Process(target=_claim_once, args=(repo, tasks, output)) for _ in range(10)]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    claimed = [output.get(timeout=1) for _ in processes]
    assert len({run_id for run_id, _, _ in claimed}) == 10
    assert len({task_id for _, task_id, _ in claimed}) == 10


def test_expired_owner_cannot_renew_or_complete_reassigned_lease(tmp_path):
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    first_run = coordinator.start_run("test", now=0)
    second_run = coordinator.start_run("test", now=2)
    task = {"id": "task-one", "goal": "do it"}

    first = coordinator.claim([task], first_run.id, ttl_s=1, now=0)
    second = coordinator.claim([task], second_run.id, ttl_s=10, now=2)

    assert first is not None and second is not None
    assert second.generation == first.generation + 1
    assert not coordinator.renew(first, ttl_s=10, now=2)
    assert not coordinator.complete(first)
    assert coordinator.renew(second, ttl_s=10, now=2)
    assert coordinator.complete(second)


def test_submit_proposals_dedupes_equivalent_tasks(tmp_path):
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo)
    run_a, run_b = db.start_run("a"), db.start_run("b")
    db.submit_proposals(run_a.id, [{"id": "A"}, {"id": "B"}], "gen-1")
    db.submit_proposals(run_b.id, [{"id": "B"}, {"id": "C"}], "gen-1")
    fingerprints = {
        row[0] for row in db.connection.execute("SELECT fingerprint FROM tasks").fetchall()
    }
    assert fingerprints == {"A", "B", "C"}


def test_activation_refuses_live_legacy_claims(tmp_path):
    repo = _repo(tmp_path / "r")
    claims = repo / ".git" / "looptight" / "claims"
    claims.mkdir(parents=True)
    (claims / "task-a.json").write_text(
        json.dumps({"schema_version": 1, "task_id": "task-a", "owner": "o", "claimed_at": time.time()}),
        encoding="utf-8",
    )
    with pytest.raises(MigrationBlocked, match="legacy"):
        Coordinator.open(repo, activate=True)


def test_activation_writes_marker_and_legacy_fails_closed(tmp_path):
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo, activate=True)
    assert db is not None
    marker = repo / ".git" / "looptight" / "coordinator-format.json"
    assert marker.is_file()

    Coordinator.open(repo, activate=True)  # idempotent

    store = ClaimStore(claim_dir(repo), "owner")
    with pytest.raises(LegacyClaimsDisabled):
        store.select([{"id": "x"}])
