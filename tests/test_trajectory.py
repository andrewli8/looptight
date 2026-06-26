"""Repo-private, per-worktree verify-trajectory store (session-native stall)."""

from __future__ import annotations

import json
import subprocess

import pytest

from looptight import trajectory


def _repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def test_record_appends_and_returns_growing_history(tmp_path):
    repo = _repo(tmp_path)
    e1 = trajectory.record(repo, "pytest -q", -3.0, {"FAILED a::x"}, passed=False)
    assert [entry["signal"] for entry in e1] == [-3.0]
    e2 = trajectory.record(repo, "pytest -q", -3.0, {"FAILED a::x"}, passed=False)
    assert [entry["signal"] for entry in e2] == [-3.0, -3.0]


def test_record_clears_on_pass(tmp_path):
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, {"FAILED a::x"}, passed=False)
    assert trajectory.record(repo, "pytest -q", None, set(), passed=True) == []
    # The next failing run starts a fresh attempt.
    assert len(trajectory.record(repo, "pytest -q", -2.0, {"FAILED a::x"}, passed=False)) == 1


def test_record_resets_on_changed_command(tmp_path):
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)
    fresh = trajectory.record(repo, "npm test", -2.0, set(), passed=False)
    assert len(fresh) == 1  # different command -> different attempt


def test_record_resets_on_stale_gap(tmp_path):
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False, now=1000.0)
    later = trajectory.record(repo, "pytest -q", -2.0, set(), passed=False, now=1000.0 + 3600)
    assert len(later) == 1  # the prior entry is stale, so a fresh attempt begins


def test_record_tolerates_a_corrupt_store(tmp_path):
    repo = _repo(tmp_path)
    path = trajectory._path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not json")
    fresh = trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)
    assert len(fresh) == 1  # a corrupt file is treated as empty, never raises


def test_record_is_a_noop_outside_git(tmp_path):
    assert trajectory.record(tmp_path, "pytest -q", -2.0, set(), passed=False) == []
    assert trajectory._path(tmp_path) is None


def test_record_write_is_atomic(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)  # seed a valid store
    tmp = trajectory._path(repo).with_suffix(".tmp")

    def boom(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr("looptight.trajectory.os.replace", boom)
    with pytest.raises(OSError):
        trajectory.record(repo, "pytest -q", -1.0, set(), passed=False)
    assert not tmp.exists()  # no stale temp left behind
    # The prior store is intact (one entry, not corrupted).
    data = json.loads(trajectory._path(repo).read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
