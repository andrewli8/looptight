"""Git checkpoint round-trip (D4) — the only test that touches real git.

Proves the "I can always get my repo back" promise: an iteration's in-progress
(uncommitted) edits can be snapshotted and later restored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import looptight.checkpoint as checkpoint_module
from looptight.checkpoint import Checkpointer


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
