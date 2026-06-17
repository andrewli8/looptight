"""Git checkpoint round-trip (D4) — the only test that touches real git.

Proves the "I can always get my repo back" promise: an iteration's in-progress
(uncommitted) edits can be snapshotted and later restored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

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
