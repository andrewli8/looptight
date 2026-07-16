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


def test_restore_defaults_to_latest_snapshot(tmp_path):
    # checkpoint.py:100 — `self.snapshots[-1]` is the latest-snapshot fallback
    # when `restore()` is called without an explicit sha.  Every existing restore
    # call in the suite either passes an explicit sha or has enabled=False / no
    # snapshots, so this arm was never exercised.
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)

    (tmp_path / "f.txt").write_text("version-1")
    sha1 = cp.snapshot()
    assert sha1

    (tmp_path / "f.txt").write_text("version-2")
    sha2 = cp.snapshot()
    assert sha2
    assert cp.snapshots[-1] == sha2

    (tmp_path / "f.txt").write_text("clobbered")
    assert cp.restore() is True  # no explicit sha — must fall back to snapshots[-1]
    assert (tmp_path / "f.txt").read_text() == "version-2"


def test_snapshot_on_clean_tree_returns_head_sha(tmp_path):
    """snapshot() on an unmodified repo returns the HEAD commit SHA."""
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    assert cp.enabled

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    head_sha = result.stdout.strip()
    assert head_sha  # sanity: repo has a commit

    sha = cp.snapshot()
    assert sha == head_sha
    assert sha in cp.snapshots


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


def test_diffstat_returns_empty_when_no_snapshots_and_no_since(tmp_path):
    # checkpoint.py:110 — `base = since or (self.snapshots[0] if self.snapshots else None)`.
    # When self.snapshots is empty and no `since` is provided, base is None and the
    # `if not base: return ""` guard must fire. No existing test exercises the empty-list
    # branch; removing `if self.snapshots else None` would raise IndexError here.
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    assert cp.snapshots == []
    assert cp.diffstat() == ""


def test_checkpoint_git_sets_git_terminal_prompt_env(tmp_path, monkeypatch):
    """_git() passes GIT_TERMINAL_PROMPT=0 so headless runs never hang on a prompt."""
    import looptight.checkpoint as cp_mod

    captured_env: dict | None = None

    def fake_run(cmd, **kwargs):
        nonlocal captured_env
        captured_env = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(cp_mod.subprocess, "run", fake_run)
    cp_mod._git(["rev-parse", "HEAD"], tmp_path)

    assert captured_env is not None
    assert captured_env.get("GIT_TERMINAL_PROMPT") == "0"


def test_save_returns_none_when_git_returns_empty_sha(tmp_path, monkeypatch):
    """checkpoint.py:88 — if not sha: return None when rev-parse exits 0 but prints nothing."""
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)
    responses = iter(
        [
            subprocess.CompletedProcess(["git", "stash"], 0, stdout="", stderr=""),
            subprocess.CompletedProcess(["git", "rev-parse"], 0, stdout="", stderr=""),
        ]
    )
    monkeypatch.setattr(checkpoint_module, "_git", lambda args, cwd: next(responses))

    assert cp.snapshot() is None
    assert cp.snapshots == []


def test_diffstat_returns_nonempty_on_successful_diff(tmp_path):
    """checkpoint.py:116 — diffstat() returns a non-empty string when the working
    tree differs from the snapshot, and the output mentions the changed filename."""
    _init_repo(tmp_path)
    cp = Checkpointer(tmp_path)

    sha = cp.snapshot()
    assert sha  # clean tree → HEAD SHA recorded

    (tmp_path / "f.txt").write_text("modified content")

    result = cp.diffstat()
    assert result  # non-empty
    assert "f.txt" in result
