"""Repository integration lock + coordinator-owned worktree tests."""

from __future__ import annotations

import subprocess
from multiprocessing import get_context

import pytest

from looptight.integration_queue import (
    CoordinationTimeout,
    IntegrationLock,
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
