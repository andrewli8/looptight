"""Repository integration lock + coordinator-owned worktree tests."""

from __future__ import annotations

import subprocess
from multiprocessing import get_context

import pytest

from looptight.coordinator import Coordinator
from looptight.integration_queue import (
    CoordinationTimeout,
    InjectedCrash,
    IntegrationLock,
    Integrator,
    Publisher,
    git_common_dir,
    integration_worktree,
    prepare_integration_worktree,
)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@t.test", *args],
        capture_output=True, text=True, check=True,
    )


def _repo_with_candidate(tmp_path):
    repo = _repo(tmp_path / "r")
    _git(repo, "checkout", "-q", "-b", "cand")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feature")
    candidate = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "main")
    return repo, candidate


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


@pytest.mark.parametrize(
    "boundary", ["after_merge", "after_commit", "after_update_ref", "after_db_update"]
)
def test_recovery_has_one_reachable_result(tmp_path, boundary):
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    assert db is not None
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)

    with pytest.raises(InjectedCrash):
        Integrator(db, crash_after=boundary).run_next(repo, "exit 0")

    Integrator(db).reconcile(repo, "exit 0")

    reachable = _git(
        repo, "log", "refs/heads/main", "--pretty=%H",
        f"--grep=Looptight-Integration-ID: {integration_id}",
    ).stdout.split()
    assert len(reachable) == 1  # exactly one reachable result regardless of crash point
    assert db.integration(integration_id).state == "complete"


def _repo_with_remote(tmp_path):
    repo, candidate = _repo_with_candidate(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)
    result = Integrator(db).run_next(repo, "exit 0")
    assert result.status == "complete"
    return repo, db, integration_id, result.result_sha


def test_publication_finalizes_without_second_push_when_remote_has_result(tmp_path):
    repo, db, integration_id, result_sha = _repo_with_remote(tmp_path)
    # Simulate the publisher having pushed the result and then crashed before finalizing.
    _git(repo, "push", "-q", "origin", f"{result_sha}:refs/heads/main")
    publication_id = db.enqueue_publication(integration_id, "origin", "refs/heads/main")

    calls = []
    Publisher(db, push=lambda *a: calls.append(a)).run_next(repo)

    assert calls == []  # remote already has the result: no second push
    assert db.publication(publication_id).state == "complete"


def test_publication_pushes_exact_result_when_remote_behind(tmp_path):
    repo, db, integration_id, result_sha = _repo_with_remote(tmp_path)
    publication_id = db.enqueue_publication(integration_id, "origin", "refs/heads/main")

    pushed = []

    def fake_push(root, remote, sha, ref):
        pushed.append((sha, ref))
        return _git(root, "push", "-q", remote, f"{sha}:{ref}").returncode

    Publisher(db, push=fake_push).run_next(repo)

    assert pushed == [(result_sha, "refs/heads/main")]  # exact result SHA, no candidate replay
    assert db.publication(publication_id).state == "complete"
