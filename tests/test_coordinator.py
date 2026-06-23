"""Repository-private SQLite coordinator tests."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from multiprocessing import get_context

import pytest

from looptight.claims import ClaimStore, LegacyClaimsDisabled, claim_dir
from looptight.coordinator import (
    Coordinator,
    IntegrationOutcome,
    MigrationBlocked,
    coordinator_path,
)


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
    assert one.connection.execute("PRAGMA user_version").fetchone()[0] == 2


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


def test_experience_records_failures_and_cooldown(tmp_path):
    coord = Coordinator.open(_repo(tmp_path / "repo"))
    assert coord is not None
    coord.record_failure("idea-a", "lint", now=1000.0)
    coord.record_failure("idea-a", "lint", now=1100.0)
    coord.record_failure("idea-b", "todo", now=1100.0)

    # within window: both recent; idea-a counted twice
    recent = coord.recent_failures(window_s=500.0, now=1200.0)
    assert recent == {"idea-a": 2, "idea-b": 1}

    # outside window: idea-a's last failure (1100) is older than now-50
    assert coord.recent_failures(window_s=50.0, now=1200.0) == {}

    assert coord.failure_counts() == {"lint": 2, "todo": 1}
    coord.close()


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


def test_finish_integration_conflict_requeues_below_cap_then_fails(tmp_path):
    db = Coordinator.open(_repo(tmp_path / "r"))
    task = {"id": "t1"}
    observed = []
    for attempt in range(1, 4):  # attempt cap = 3
        run = db.start_run(f"r{attempt}")
        lease = db.claim([task], run.id, ttl_s=60)
        assert lease is not None and lease.generation == attempt
        integration_id = db.enqueue_integration(lease, "refs/heads/main", f"sha{attempt}")
        db.finish_integration(
            integration_id,
            IntegrationOutcome(integration_id, "conflict", error="conflict", retained_worktree="wt"),
            max_attempts=3,
        )
        assert db.current_lease(lease._row_id) is None  # fenced lease released
        observed.append(
            db.connection.execute("SELECT state FROM tasks WHERE fingerprint = 't1'").fetchone()[0]
        )

    assert observed == ["queued", "queued", "failed"]  # requeued below the cap, failed at it
    # A failed task is no longer claimable.
    assert db.claim([task], db.start_run("again").id, ttl_s=60) is None


def test_reap_abandoned_releases_dead_run_leases(tmp_path):
    db = Coordinator.open(_repo(tmp_path / "r"))
    run = db.start_run("dead", now=0)
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=100000, now=0)  # long TTL: only reap can free it
    assert lease is not None

    db.heartbeat(run.id, now=100)
    assert db.reap_abandoned(older_than_s=50, now=120) == ()  # heartbeat 100 >= cutoff 70: spared
    assert db.current_lease(lease._row_id) is not None

    reaped = db.reap_abandoned(older_than_s=50, now=200)  # heartbeat 100 < cutoff 150: stale
    assert run.id in reaped
    assert db.current_lease(lease._row_id) is None  # lease released, task requeued

    fresh = db.start_run("fresh", now=200)
    assert db.claim([{"id": "t1"}], fresh.id, ttl_s=60, now=200) is not None
