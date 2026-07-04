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
    CoordinationError,
    Coordinator,
    CoordinatorUnavailable,
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
    assert one.connection.execute("PRAGMA user_version").fetchone()[0] == 4


def test_open_reports_a_corrupt_database_as_unavailable(tmp_path):
    # A corrupt/truncated coordinator.db raises sqlite3.DatabaseError ("not a database"),
    # which is NOT an OperationalError, so the lock-retry loop does not absorb it. open must
    # convert it to a clean CoordinatorUnavailable, not let a raw sqlite traceback escape.
    repo = _repo(tmp_path / "r")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database")

    with pytest.raises(CoordinatorUnavailable) as exc:
        Coordinator.open(repo)
    assert str(path) in str(exc.value)


def test_coordinator_path_sets_terminal_prompt_env(tmp_path):
    # coordinator_path's `git rev-parse` must pass GIT_TERMINAL_PROMPT=0 so a headless run
    # (next/status/goal all open the coordinator) can't block on a credential prompt.
    from unittest.mock import patch

    import looptight.coordinator as coord

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    with patch.object(coord.subprocess, "run", fake_run):
        coordinator_path(tmp_path)
    assert captured.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


def test_active_lease_for_owner_returns_the_owners_live_lease(tmp_path):
    # The Stop hook finds the task this worktree's session claimed via the owner, not the run id.
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo)
    assert db is not None
    run = db.start_run("session", owner="owner-x")
    db.claim(
        [{"id": "t1", "evidence": "Evidence: src/foo.py:1", "goal": "fix foo"}],
        run.id,
        ttl_s=60,
    )

    lease = db.active_lease_for_owner("owner-x")
    assert lease is not None
    assert lease.payload["id"] == "t1"
    assert lease.payload["evidence"] == "Evidence: src/foo.py:1"
    assert db.active_lease_for_owner("nobody") is None  # a different owner holds nothing


def test_coordinator_path_is_none_outside_git(tmp_path):
    assert coordinator_path(tmp_path) is None
    assert Coordinator.open(tmp_path) is None


def test_coordinator_path_is_none_when_git_is_not_installed(tmp_path, monkeypatch):
    # git not on PATH (OSError on spawn) must make the coordinator gracefully
    # unavailable — the loop falls back to file claims rather than crashing. Distinct
    # from the not-a-repo path (git present, returncode != 0).
    import looptight.coordinator as coord_mod

    repo = _repo(tmp_path / "repo")  # build the repo first, before git "disappears"

    def raise_oserror(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(coord_mod.subprocess, "run", raise_oserror)
    assert coordinator_path(repo) is None


def test_coordinator_open_closes_connection_on_base_exception(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import looptight.coordinator as coord_mod

    repo = _repo(tmp_path / "repo")

    mock_conn = MagicMock()
    monkeypatch.setattr(coord_mod.sqlite3, "connect", lambda *a, **kw: mock_conn)
    monkeypatch.setattr(coord_mod, "_initialize_schema", lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        Coordinator.open(repo)

    mock_conn.close.assert_called_once()


def test_coordinator_unknown_id_lookups_are_safe_no_ops(tmp_path):
    # A stale or mistaken id must be a safe no-op, not a crash: lease_for returns None
    # when no lease matches, and finish_integration returns without effect on an
    # unknown integration id.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    assert coordinator.lease_for("no-such-fingerprint", "no-such-run") is None
    # Unknown integration id: early return, no raise, nothing changed.
    coordinator.finish_integration("no-such-id", IntegrationOutcome("no-such-id", "complete"))
    assert coordinator.lease_for("no-such-fingerprint", "no-such-run") is None


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


def test_publications_reserved_columns_are_kept(tmp_path):
    # observed_local_sha and reconciliation_sha are reserved for a future push-reconciliation
    # feature: kept (not dropped, so the v4 schema stays unambiguous across DBs), never read/written.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    cols = {row[1] for row in coordinator.connection.execute("PRAGMA table_info(publications)")}
    assert {"observed_local_sha", "reconciliation_sha"} <= cols  # present (reserved, not dropped)


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


def test_recent_failures_counts_only_in_window_failures(tmp_path):
    """COUNT should be windowed: an old failure + a recent failure → count 1, not 2."""
    coord = Coordinator.open(_repo(tmp_path / "repo"))
    assert coord is not None
    coord.record_failure("idea-a", "lint", now=100.0)   # outside window
    coord.record_failure("idea-a", "lint", now=1100.0)  # inside window
    # cutoff = 1200 - 500 = 700; only the failure at 1100 is in-window
    recent = coord.recent_failures(window_s=500.0, now=1200.0)
    assert recent == {"idea-a": 1}
    coord.close()


def test_record_failure_captures_reason_and_reports_dominant_per_category(tmp_path):
    coord = Coordinator.open(_repo(tmp_path / "repo"))
    assert coord is not None
    coord.record_failure("idea-a", "status-next", reason="scope", now=1.0)
    coord.record_failure("idea-b", "status-next", reason="scope", now=2.0)
    coord.record_failure("idea-c", "status-next", reason="timeout", now=3.0)
    coord.record_failure("idea-d", "lint", reason="fail", now=4.0)
    # dominant (most frequent) failure reason per category
    assert coord.failure_reasons() == {"status-next": "scope", "lint": "fail"}
    # backward compatible: a reasonless failure is still recorded but adds no reason
    coord.record_failure("idea-e", "todo", now=5.0)
    assert "todo" not in coord.failure_reasons()
    assert coord.recent_failures(window_s=100.0, now=5.0).get("idea-e") == 1
    coord.close()


def test_migration_v2_to_v3_adds_reason_column(tmp_path):
    repo = _repo(tmp_path / "repo")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.executescript(
        """CREATE TABLE experience (
            id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL, category TEXT NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('failed')), created_at REAL NOT NULL
        );
        PRAGMA user_version = 2;"""
    )
    raw.close()

    coord = Coordinator.open(repo)
    assert coord is not None
    # would raise "no such column: reason" if the v2->v3 migration didn't run
    coord.record_failure("idea-x", "status-next", reason="timeout", now=1.0)
    assert coord.failure_reasons() == {"status-next": "timeout"}
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


def test_claim_spares_a_different_owners_live_lease(tmp_path):
    # The DB is shared across a repo's worktrees, which at different commits/branches
    # see divergent candidate sets. A run must NOT complete or un-lease a task a
    # DIFFERENT owner (worktree) holds a live lease on just because it is absent from
    # this caller's set — that silently loses the other worktree's in-flight work.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    run_a = coordinator.start_run("a", owner="worktree-A", now=0)
    run_b = coordinator.start_run("b", owner="worktree-B", now=0)
    lease_x = coordinator.claim(
        [{"id": "task-x", "goal": "x"}], run_a.id, ttl_s=100000, now=0, owner="worktree-A"
    )
    assert lease_x is not None
    # run B (a different owner) claims a divergent set [Y]; X is out of B's set but live.
    lease_y = coordinator.claim(
        [{"id": "task-y", "goal": "y"}], run_b.id, ttl_s=60, now=1, owner="worktree-B"
    )
    assert lease_y is not None
    # A's live lease survives B's sweep because B is a different owner; X stays leased.
    assert coordinator.renew(lease_x, ttl_s=100000, now=2) is True
    state = coordinator.connection.execute(
        "SELECT state FROM tasks WHERE fingerprint = ?", ("task-x",)
    ).fetchone()
    assert state is not None and state[0] == "leased"


def test_claim_still_completes_a_same_owner_out_of_set_task(tmp_path):
    # The single-writer reconcile: the SAME owner (same worktree) running `next` after
    # a task is removed from its set must still retire that task's stale claim, even
    # though a prior run of the same owner holds its (still-live) lease.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    run1 = coordinator.start_run("s", owner="W", now=0)
    run2 = coordinator.start_run("s", owner="W", now=0)
    assert coordinator.claim(
        [{"id": "x", "goal": "x"}], run1.id, ttl_s=100000, now=0, owner="W"
    ) is not None
    # run2 (same owner W) claims a divergent set; x is no longer proposed → retired.
    coordinator.claim([{"id": "y", "goal": "y"}], run2.id, ttl_s=60, now=1, owner="W")
    state = coordinator.connection.execute(
        "SELECT state FROM tasks WHERE fingerprint = ?", ("x",)
    ).fetchone()
    assert state is not None and state[0] == "complete"


def test_enqueue_integration_is_fenced_to_the_live_lease(tmp_path):
    # A worker whose lease was superseded (expired, reclaimed by another run) must
    # not enqueue an integration, or it would integrate stale or conflicting work.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None
    first_run = coordinator.start_run("test", now=0)
    second_run = coordinator.start_run("test", now=2)
    task = {"id": "task-one", "goal": "do it"}

    first = coordinator.claim([task], first_run.id, ttl_s=1, now=0)
    second = coordinator.claim([task], second_run.id, ttl_s=10, now=2)
    assert second.generation == first.generation + 1  # first is now stale

    with pytest.raises(CoordinationError):
        coordinator.enqueue_integration(first, "refs/heads/main", "deadbeef")
    assert coordinator.enqueue_integration(second, "refs/heads/main", "deadbeef")  # live lease ok


def test_enqueue_publication_requires_a_complete_integration(tmp_path):
    # Only a completed integration (with a result sha) may be queued for the
    # remote; an unknown or not-yet-complete integration is rejected, so unverified
    # work is never published.
    coordinator = Coordinator.open(_repo(tmp_path / "repo"))
    assert coordinator is not None

    with pytest.raises(CoordinationError):
        coordinator.enqueue_publication("unknown-id", "origin", "refs/heads/main")

    run = coordinator.start_run("test", now=0)
    lease = coordinator.claim([{"id": "t", "goal": "g"}], run.id, ttl_s=60, now=0)
    integ_id = coordinator.enqueue_integration(lease, "refs/heads/main", "sha")
    # the integration is queued, not yet complete -> publication is refused
    with pytest.raises(CoordinationError):
        coordinator.enqueue_publication(integ_id, "origin", "refs/heads/main")


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
    with pytest.raises(MigrationBlocked, match="legacy") as exc:
        Coordinator.open(repo, activate=True)
    # The exception carries the reason; the command supplies the "cannot activate
    # the coordinator:" framing. If the exception repeats it, cmd_migrate doubles
    # the prefix in the user-facing message.
    assert "live legacy claims exist" in str(exc.value)
    assert "cannot activate the coordinator" not in str(exc.value)


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


def test_migration_v1_to_v2_adds_experience_table(tmp_path):
    repo = _repo(tmp_path / "repo")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.executescript("PRAGMA user_version = 1;")  # empty v1 DB
    raw.close()

    coord = Coordinator.open(repo)
    assert coord is not None
    # would raise sqlite OperationalError "no such table" if the migration didn't run
    coord.record_failure("idea-x", "lint", now=1.0)
    assert coord.recent_failures(window_s=100.0, now=2.0) == {"idea-x": 1}
    coord.close()


def test_migration_v3_to_v4_adds_owner_column(tmp_path):
    repo = _repo(tmp_path / "repo")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.executescript(
        """CREATE TABLE runs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('active','complete','failed','abandoned')),
            pid INTEGER NOT NULL, heartbeat REAL NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('queued','leased','complete','failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)
        );
        CREATE TABLE leases (
            task_id INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            generation INTEGER NOT NULL CHECK (generation > 0), expires_at REAL NOT NULL
        );
        PRAGMA user_version = 3;"""  # a v3 runs table has no owner column
    )
    raw.close()

    coord = Coordinator.open(repo)
    assert coord is not None
    # The v3->v4 migration added runs.owner and bumped the version.
    columns = {row[1] for row in coord.connection.execute("PRAGMA table_info(runs)")}
    assert "owner" in columns, "v3->v4 migration did not add runs.owner"
    assert coord.connection.execute("PRAGMA user_version").fetchone()[0] == 4
    # An owner-scoped claim works on the upgraded DB.
    run = coord.start_run("s", owner="W")
    lease = coord.claim([{"id": "t", "goal": "g"}], run.id, ttl_s=60, owner="W")
    assert lease is not None
    coord.close()


def test_migrate_v3_to_v4_skips_gracefully_when_runs_table_absent(tmp_path):
    # A partial or re-applied migration may present a v3 DB where the `runs` table was
    # never created. _migrate_3_to_4 guards with `if table is not None` (coordinator.py:124)
    # and must skip the ALTER silently, still bumping to v4, so Coordinator.open succeeds.
    repo = _repo(tmp_path / "repo")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.executescript(
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('queued','leased','complete','failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)
        );
        CREATE TABLE experience (
            id INTEGER PRIMARY KEY, idea_id TEXT NOT NULL, outcome TEXT NOT NULL,
            recorded_at REAL NOT NULL, reason TEXT NOT NULL DEFAULT ''
        );
        PRAGMA user_version = 3;"""
        # No `runs` table — simulates the absent-table branch in _migrate_3_to_4.
    )
    raw.close()

    coord = Coordinator.open(repo)
    assert coord is not None, "open should succeed even when `runs` table is absent"
    assert coord.connection.execute("PRAGMA user_version").fetchone()[0] == 4
    coord.close()


def test_open_rejects_a_newer_unsupported_schema_version(tmp_path):
    # A DB written by a *newer* looptight (user_version beyond SCHEMA_VERSION, e.g. after
    # a downgrade) must fail to open with a clean CoordinatorUnavailable carrying an upgrade
    # hint, not a raw version-skew RuntimeError traceback.
    repo = _repo(tmp_path / "repo")
    path = coordinator_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.executescript("PRAGMA user_version = 99;")  # a future, unknown schema
    raw.close()

    with pytest.raises(CoordinatorUnavailable, match="newer looptight"):
        Coordinator.open(repo)


def test_coordination_scope_reports_three_states(tmp_path):
    from looptight.claims import MARKER_NAME
    from looptight.coordinator import coordination_scope, coordinator_path

    plain = tmp_path / "plain"
    plain.mkdir()
    assert coordination_scope(plain) == "none"  # outside Git

    repo = tmp_path / "repo"
    _repo(repo)  # the fixture creates the directory and runs git init
    assert coordination_scope(repo) == "file-claims"  # Git, coordinator not activated

    marker = coordinator_path(repo).parent
    marker.mkdir(parents=True, exist_ok=True)
    (marker / MARKER_NAME).write_text("{}", encoding="utf-8")
    assert coordination_scope(repo) == "coordinator"  # marker present
