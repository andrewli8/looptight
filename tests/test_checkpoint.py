"""Git checkpoint round-trip (D4) — the only test that touches real git.

Proves the tracked-file checkpoint promise: an iteration's in-progress
(uncommitted) edits to tracked files can be snapshotted and later restored.
Untracked files are out of scope — they are neither captured nor removed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import looptight.checkpoint as checkpoint_module
from looptight.checkpoint import Checkpointer, is_git_primary_worktree, is_git_repo


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _git(["init", "-q"], path)
    _git(["config", "user.email", "t@t.test"], path)
    _git(["config", "user.name", "t"], path)
    _git(["config", "commit.gpgsign", "false"], path)  # don't depend on a signing setup
    (path / "f.txt").write_text("committed")
    _git(["add", "-A"], path)
    _git(["commit", "-q", "--no-gpg-sign", "-m", "init"], path)


def test_is_git_repo_true_inside_repo_false_outside(tmp_path):
    outside = tmp_path / "plain"
    outside.mkdir()
    assert is_git_repo(outside) is False

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    assert is_git_repo(repo) is True


def test_is_git_primary_worktree_distinguishes_primary_linked_and_non_repo(tmp_path):
    outside = tmp_path / "plain"
    outside.mkdir()
    assert is_git_primary_worktree(outside) is False

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    assert is_git_primary_worktree(repo) is True

    # A linked worktree shares the common dir but has its own git dir, so it is
    # not the primary worktree — the case that actually exercises the comparison.
    linked = tmp_path / "linked"
    _git(["worktree", "add", "-q", str(linked)], repo)
    assert is_git_primary_worktree(linked) is False


def test_snapshot_then_restore_recovers_uncommitted_work(tmp_path):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    assert cp.enabled

    (tmp_path / "f.txt").write_text("work in progress")
    sha = cp.snapshot()
    assert sha

    (tmp_path / "f.txt").write_text("clobbered")
    assert cp.restore(sha) is True
    assert (tmp_path / "f.txt").read_text() == "work in progress"


def test_checkpointer_is_a_noop_outside_git(tmp_path):
    cp = Checkpointer(tmp_path)  # tmp_path is not a git repo
    assert cp.enabled is False
    assert cp.snapshot() is None
    assert cp.restore() is False


def test_restore_returns_false_when_enabled_but_no_snapshots(tmp_path):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    assert cp.enabled is True
    assert cp.snapshots == []
    assert cp.restore() is False


def test_checkpointer_is_a_noop_when_git_cannot_launch(tmp_path, monkeypatch):
    def fail_to_launch(*args, **kwargs):
        raise FileNotFoundError("git is not installed")

    monkeypatch.setattr(subprocess, "run", fail_to_launch)

    cp = Checkpointer(tmp_path)

    assert cp.enabled is False
    assert cp.snapshot() is None
    assert cp.restore() is False


def test_snapshot_returns_none_when_stash_create_fails(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    calls = []

    def failing_git(args, cwd):
        calls.append(args)
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="failed")

    monkeypatch.setattr(checkpoint_module, "_git", failing_git)

    assert cp.snapshot() is None
    assert cp.snapshots == []
    assert calls == [["stash", "create", "looptight checkpoint"]]


def test_clean_snapshot_returns_none_when_head_lookup_fails(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    responses = iter(
        [
            subprocess.CompletedProcess(["git", "stash"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["git", "rev-parse"], 1, stdout="", stderr="failed"),
        ]
    )
    monkeypatch.setattr(checkpoint_module, "_git", lambda args, cwd: next(responses))

    assert cp.snapshot() is None
    assert cp.snapshots == []


def test_diffstat_returns_empty_when_diff_command_fails(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    cp.snapshots.append("deadbeef")

    def failing_git(args, cwd):
        return subprocess.CompletedProcess(
            ["git", *args], 1, stdout="stale diff output", stderr="bad revision"
        )

    monkeypatch.setattr(checkpoint_module, "_git", failing_git)

    assert cp.diffstat() == ""
