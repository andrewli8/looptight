"""Repository integration lock + coordinator-owned worktree tests."""

from __future__ import annotations

import subprocess
from multiprocessing import get_context

import pytest

from looptight.coordinator import Coordinator
from looptight.integration_queue import (
    CoordinationTimeout,
    IntegrationLock,
    Integrator,
    git_common_dir,
    integration_worktree,
    prepare_integration_worktree,
)


def _repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@t.test", "commit",
         "--allow-empty", "-qm", "init"],
        cwd=path,
        check=True,
    )
    return path


def _hold_lock(common, entered, release):
    with IntegrationLock.acquire(common, timeout_s=2):
        entered.set()
        release.wait(3)


def test_second_process_cannot_enter_integration_lock(tmp_path):
    repo = _repo(tmp_path / "r")
    common = git_common_dir(repo)
    ctx = get_context()
    entered, release = ctx.Event(), ctx.Event()
    holder = ctx.Process(target=_hold_lock, args=(common, entered, release))
    holder.start()
    try:
        assert entered.wait(3)
        with pytest.raises(CoordinationTimeout):
            with IntegrationLock.acquire(common, timeout_s=0.05):
                pass
    finally:
        release.set()
        holder.join(5)


def test_lock_is_reacquirable_after_release(tmp_path):
    repo = _repo(tmp_path / "r")
    common = git_common_dir(repo)
    with IntegrationLock.acquire(common, timeout_s=1):
        pass
    with IntegrationLock.acquire(common, timeout_s=1) as lock:  # releases on exit, no timeout
        assert lock.path.exists()


def test_integration_worktree_is_detached_and_under_coordinator_dir(tmp_path):
    repo = _repo(tmp_path / "r")
    common = git_common_dir(repo)
    path, sha = prepare_integration_worktree(repo, "refs/heads/main")

    assert path.is_relative_to(common / "looptight" / "integration")
    assert len(sha) == 40
    # Detached HEAD has no symbolic ref — it is not a user worktree on a branch.
    assert subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=path, capture_output=True
    ).returncode != 0


def test_prepare_integration_worktree_is_stable_and_clean(tmp_path):
    repo = _repo(tmp_path / "r")
    first, _ = prepare_integration_worktree(repo, "refs/heads/main")
    second, _ = prepare_integration_worktree(repo, "refs/heads/main")
    assert first == second  # same path reused for the same target ref
    assert integration_worktree(repo, "refs/heads/main") == first


def test_oldest_integration_runs_first(tmp_path):
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo)
    assert db is not None
    run_a, run_b = db.start_run("a"), db.start_run("b")
    tasks = [{"id": "t1"}, {"id": "t2"}]
    lease_a = db.claim(tasks, run_a.id, ttl_s=60)
    lease_b = db.claim(tasks, run_b.id, ttl_s=60)
    assert lease_a is not None and lease_b is not None and lease_a.task_id != lease_b.task_id

    first = db.enqueue_integration(lease_a, "refs/heads/main", "sha-a")
    db.enqueue_integration(lease_b, "refs/heads/main", "sha-b")

    assert Integrator(db).next_id() == first  # global FIFO by enqueue order


def test_stale_fence_is_superseded_and_new_owner_keeps_lease(tmp_path):
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo)
    assert db is not None
    run1, run2 = db.start_run("one"), db.start_run("two")
    lease1 = db.claim([{"id": "t1"}], run1.id, ttl_s=1, now=0)
    integration_id = db.enqueue_integration(lease1, "refs/heads/main", "sha1")
    # Lease1 expires; run2 reclaims with a fresh generation before integration runs.
    lease2 = db.claim([{"id": "t1"}], run2.id, ttl_s=1, now=2)
    assert lease2.generation == lease1.generation + 1

    record = db.integration(integration_id)
    outcome = Integrator(db).run_record(record)

    assert outcome.status == "superseded"
    assert db.current_lease(lease1._row_id).run_id == run2.id  # new owner's lease intact
