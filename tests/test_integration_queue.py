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
    _is_ancestor,
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


def test_trailer_lookups_return_none_on_git_failure(tmp_path, monkeypatch):
    # Crash recovery must not blow up on a transient git error: both trailer lookups
    # degrade to None when their git command fails.
    from looptight import integration_queue as iq

    repo = _repo(tmp_path / "r")
    monkeypatch.setattr(
        iq, "_git", lambda *a, **k: subprocess.CompletedProcess(["git"], 1, "", "boom")
    )
    assert iq._trailer_commit_on_ref(repo, "main", "some-id") is None
    assert iq._committed_result_in_worktree(repo, "some-id") is None


def test_prepare_integration_worktree_rejects_an_unresolvable_ref(tmp_path):
    # The integrator must not prepare a worktree for a target ref that does not exist:
    # rev-parse --verify fails and it raises a clear IntegrationError.
    from looptight.integration_queue import IntegrationError, prepare_integration_worktree

    repo = _repo(tmp_path / "r")
    with pytest.raises(IntegrationError):
        prepare_integration_worktree(repo, "refs/heads/does-not-exist")


def test_integration_queue_handles_git_failures(tmp_path, monkeypatch):
    # The durable integrator must not crash on a git failure: git_common_dir raises a clear
    # IntegrationError outside a repo, and _git returns code 127 when git is not on PATH.
    from looptight import integration_queue as iq

    with pytest.raises(iq.IntegrationError):
        iq.git_common_dir(tmp_path)  # tmp_path is not a git repository

    def raise_oserror(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(iq.subprocess, "run", raise_oserror)
    result = iq._git(tmp_path, "status")
    assert result.returncode == 127
    assert "git not found" in result.stderr


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


def test_reconcile_fences_a_superseded_lease(tmp_path):
    # A crash mid-merge leaves the record `integrating` with nothing committed. If the run
    # is then reaped and a new owner reclaims the task at a fresh generation, reconcile must
    # NOT re-merge/commit the stale candidate under a lease it no longer owns — it must finish
    # `superseded`, exactly as the live `_run` path does. Otherwise the same task double-applies.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    assert db is not None
    run1 = db.start_run("one")
    lease1 = db.claim([{"id": "t1"}], run1.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease1, "refs/heads/main", candidate)

    with pytest.raises(InjectedCrash):
        Integrator(db, crash_after="after_merge").run_next(repo, "exit 0")
    assert db.integration(integration_id).state == "integrating"
    ref_before = _git(repo, "rev-parse", "refs/heads/main").stdout.strip()

    # run1 dies, is reaped, and a new owner reclaims t1 at a higher generation.
    db.connection.execute("UPDATE runs SET heartbeat = 0 WHERE id = ?", (run1.id,))
    assert run1.id in db.reap_abandoned(older_than_s=1, now=10_000)
    run2 = db.start_run("two")
    lease2 = db.claim([{"id": "t1"}], run2.id, ttl_s=60)
    assert lease2.generation == lease1.generation + 1

    outcomes = Integrator(db).reconcile(repo, "exit 0")

    assert [o.status for o in outcomes] == ["superseded"]
    assert db.current_lease(lease2._row_id).run_id == run2.id  # new owner's lease intact
    # the stale candidate never landed: the target ref is unchanged
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == ref_before


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


def test_reconcile_recovers_from_persisted_result_sha_when_worktree_is_reset(tmp_path):
    # After a crash between commit and ref-advance, recovery must not depend on the shared
    # per-target-ref worktree — a later integration to the same ref resets it. The committed
    # result_sha is recorded durably, so reconcile advances the ref from it without re-merging.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    assert db is not None
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)

    with pytest.raises(InjectedCrash):
        Integrator(db, crash_after="after_commit").run_next(repo, "exit 0")

    rec = db.integration(integration_id)
    assert rec.state == "committed"  # commit recorded durably, not just in the worktree
    assert rec.result_sha

    # A later integration to the same ref resets the shared worktree, destroying the crashed
    # commit from the worktree HEAD before reconcile can read it.
    wt = integration_worktree(repo, "refs/heads/main")
    _git(wt, "reset", "--hard", "main")

    outcomes = Integrator(db).reconcile(repo, "exit 0")

    assert [o.status for o in outcomes] == ["complete"]
    # the ref advanced to the exact persisted result, with no re-merge
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == rec.result_sha
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
    assert result.status == "complete", f"integration failed: {result.status}: {result.error}"
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


def test_publication_push_rejection_retries_bounded_then_fails_without_force(tmp_path):
    repo, db, integration_id, result_sha = _repo_with_remote(tmp_path)
    publication_id = db.enqueue_publication(integration_id, "origin", "refs/heads/main")

    attempts = []

    def rejecting_push(root, remote, sha, ref):
        attempts.append((sha, ref))
        return 1  # remote keeps rejecting (non-fast-forward); no force is ever used

    Publisher(db, push=rejecting_push).run_next(repo)

    # Bounded re-fetch+retry of the exact SHA — never a force flag, never the candidate — then fail.
    assert attempts == [(result_sha, "refs/heads/main")] * 3
    assert db.publication(publication_id).state == "failed"


def test_publication_recovers_when_a_transient_rejection_clears(tmp_path):
    # The common case: the remote moved between fetch and push (CI / another session). A bounded
    # non-force retry recovers instead of stranding the integrated result for manual reconcile.
    repo, db, integration_id, result_sha = _repo_with_remote(tmp_path)
    publication_id = db.enqueue_publication(integration_id, "origin", "refs/heads/main")

    calls = []

    def flaky_push(root, remote, sha, ref):
        calls.append(sha)
        return 1 if len(calls) == 1 else 0  # first push rejected, the retry succeeds

    outcome = Publisher(db, push=flaky_push).run_next(repo)

    assert outcome.status == "complete"
    assert db.publication(publication_id).state == "complete"
    assert calls == [result_sha, result_sha]  # one reject, one success; exact SHA both times


def test_integration_merge_conflict_aborts_and_retains(tmp_path):
    repo = _repo(tmp_path / "r")
    (repo / "f.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", "cand")
    (repo / "f.txt").write_text("candidate\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "candidate change")
    candidate = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("mainline\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "main change")

    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)

    outcome = Integrator(db).run_next(repo, "exit 0")

    assert outcome.status == "conflict"
    assert outcome.retained_worktree is not None
    assert db.current_lease(lease._row_id) is None  # fenced lease released on conflict
    assert db.integration(integration_id).state == "conflict"


def test_run_record_requires_root_for_non_superseded(tmp_path):
    repo = _repo(tmp_path / "r")
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    record = db.integration(db.enqueue_integration(lease, "refs/heads/main", "sha"))

    # Lease still owned → not superseded → a clear ValueError, not a stripped assert.
    with pytest.raises(ValueError, match="root and verify"):
        Integrator(db).run_record(record)


def test_integration_commits_with_deterministic_identity(tmp_path):
    # The merge commit must carry looptight's own identity so integration works even
    # where no ambient git user is configured (CI/containers).
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    db.enqueue_integration(lease, "refs/heads/main", candidate)

    outcome = Integrator(db).run_next(repo, "exit 0")

    assert outcome.status == "complete"
    committer = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%cn", outcome.result_sha],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert committer == "looptight"


def test_landed_writes_outcome_trailer(tmp_path):
    # After a complete integration, the carrying commit must contain the idea's
    # outcome trailer so outcomes are visible in git log.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1", "idea_id": "idea-xyz", "source": "metacog"}], run.id, ttl_s=60)
    db.enqueue_integration(lease, "refs/heads/main", candidate)

    outcome = Integrator(db).run_next(repo, "exit 0")

    assert outcome.status == "complete"
    body = _git(repo, "log", "refs/heads/main", "-1", "--pretty=%B").stdout
    assert "Looptight-Outcome: idea-xyz landed" in body
    assert "landed metacog" in body  # the task source is recorded for category yield


def test_failed_integration_records_failure(tmp_path):
    # After a failed integration (verify fails), coordinator must record the failure
    # so the metacognitive loop can track idea quality.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1", "idea_id": "idea-bad", "source": "metacog"}], run.id, ttl_s=60)
    db.enqueue_integration(lease, "refs/heads/main", candidate)

    outcome = Integrator(db).run_next(repo, "exit 1")  # failing verify

    assert outcome.status == "failed"
    assert db.recent_failures(window_s=10_000.0) == {"idea-bad": 1}


def test_record_failure_error_does_not_break_integration(tmp_path, monkeypatch):
    # If record_failure raises (e.g., db locked), integration must still finalize cleanly.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1", "idea_id": "idea-bad", "source": "metacog"}], run.id, ttl_s=60)
    db.enqueue_integration(lease, "refs/heads/main", candidate)

    def boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(db, "record_failure", boom)
    integrator = Integrator(db)
    outcome = integrator.run_next(repo, "exit 1")  # failing verify

    assert outcome.status == "failed"  # finalized cleanly despite record_failure raising


def test_update_ref_cas_conflict_when_target_advances(tmp_path, monkeypatch):
    # The ref advance is a compare-and-swap: update-ref carries `observed` as the
    # old value, so if a racing integrator moved the target ref after we observed
    # it, the CAS must fail closed (conflict/superseded) and NOT clobber the other
    # integrator's commit.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)

    integrator = Integrator(db)
    original = integrator._maybe_crash
    racing = []

    def advance_then_crash(boundary):
        if boundary == "after_commit":
            # A racing integrator advances the target ref between our commit and our
            # compare-and-swap update-ref, invalidating the observed old value.
            _git(repo, "commit", "--allow-empty", "-qm", "racing advance")
            racing.append(_git(repo, "rev-parse", "refs/heads/main").stdout.strip())
        return original(boundary)

    monkeypatch.setattr(integrator, "_maybe_crash", advance_then_crash)

    outcome = integrator.run_next(repo, "exit 0")

    assert outcome.status == "conflict"
    assert outcome.result_sha is None  # nothing published on a lost CAS
    # The error reflects the failed compare-and-swap (git's "expected" old value),
    # or the fallback superseded message when git is quiet.
    assert "expected" in (outcome.error or "") or "superseded" in (outcome.error or "")
    assert db.integration(integration_id).state == "conflict"
    # The CAS refused to overwrite the racing commit: main still points at it.
    main_after = _git(repo, "rev-parse", "refs/heads/main").stdout.strip()
    assert main_after == racing[0]


def test_reconcile_ref_advance_is_a_cas_against_a_racing_advance(tmp_path):
    # Crash recovery re-advances the ref with the same compare-and-swap. If another
    # integrator advanced the target ref while we were down, reconcile must fail
    # closed (conflict) instead of clobbering the racing commit.
    repo, candidate = _repo_with_candidate(tmp_path)
    db = Coordinator.open(repo)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)

    # Crash after the merge is committed in the worktree but before the ref advances.
    with pytest.raises(InjectedCrash):
        Integrator(db, crash_after="after_commit").run_next(repo, "exit 0")

    # A racing integrator advances the target ref while we are down.
    _git(repo, "commit", "--allow-empty", "-qm", "racing advance")
    racing = _git(repo, "rev-parse", "refs/heads/main").stdout.strip()

    outcomes = Integrator(db).reconcile(repo, "exit 0")

    assert len(outcomes) == 1
    assert outcomes[0].status == "conflict"
    assert "target advanced" in (outcomes[0].error or "")
    assert db.integration(integration_id).state != "complete"
    # The racing commit was not overwritten.
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == racing


def test_git_runs_non_interactively(tmp_path, monkeypatch):
    # A headless push/fetch must never block on a credential prompt: _git sets
    # GIT_TERMINAL_PROMPT=0 so git fails fast instead of hanging for input.
    import looptight.integration_queue as iq

    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(iq.subprocess, "run", fake_run)
    iq._git(tmp_path, "status")
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_is_ancestor_returns_false_on_empty_sha(tmp_path, monkeypatch):
    import looptight.integration_queue as iq

    called = []

    def fake_git(*args, **kwargs):
        called.append(args)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(iq, "_git", fake_git)
    assert _is_ancestor(tmp_path, "", "abc") is False
    assert _is_ancestor(tmp_path, "abc", "") is False
    assert called == [], "git must not be invoked when either SHA is empty"
