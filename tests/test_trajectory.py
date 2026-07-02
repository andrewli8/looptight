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


def test_record_resets_on_changed_task(tmp_path):
    # The repo's verify command is constant, so without task scoping a second task would inherit
    # the first's abandoned trajectory. A different claimed task starts a fresh attempt.
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False, task="idea-A")
    trajectory.record(repo, "pytest -q", -1.0, set(), passed=False, task="idea-A")
    fresh = trajectory.record(repo, "pytest -q", -5.0, set(), passed=False, task="idea-B")
    assert len(fresh) == 1  # different task -> different attempt, no bleed
    # Same task still accumulates.
    same = trajectory.record(repo, "pytest -q", -4.0, set(), passed=False, task="idea-B")
    assert len(same) == 2


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


def test_clear_drops_trajectory(tmp_path):
    repo = _repo(tmp_path)
    # Seed two entries so the store is non-trivial.
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)
    trajectory.record(repo, "pytest -q", -1.0, set(), passed=False)
    trajectory.clear(repo)
    # After clearing, the next failing record starts a fresh single-entry attempt.
    fresh = trajectory.record(repo, "pytest -q", -3.0, set(), passed=False)
    assert len(fresh) == 1


def test_record_treats_non_numeric_updated_at_as_stale(tmp_path):
    repo = _repo(tmp_path)
    path = trajectory._path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write a trajectory whose updated_at is not a number (defensive path at :72).
    path.write_text(
        '{"schema_version": 1, "command": "pytest -q", "updated_at": "not-a-number",'
        ' "entries": [{"signal": -2.0, "failures": []}]}\n',
        encoding="utf-8",
    )
    fresh = trajectory.record(repo, "pytest -q", -1.0, set(), passed=False)
    assert len(fresh) == 1  # corrupt updated_at -> stale -> fresh attempt


def test_record_write_is_atomic(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)  # seed a valid store
    tmp = trajectory._path(repo).with_suffix(".tmp")

    def boom(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)
    with pytest.raises(OSError):
        trajectory.record(repo, "pytest -q", -1.0, set(), passed=False)
    assert not tmp.exists()  # no stale temp left behind
    # The prior store is intact (one entry, not corrupted).
    data = json.loads(trajectory._path(repo).read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1


def test_trajectory_read_returns_none_for_wrong_schema_version(tmp_path):
    # Valid JSON but an unrecognised schema_version is treated as no prior attempt,
    # so a forward-incompatible file cannot poison value-aware stopping.
    path = tmp_path / "traj.json"
    path.write_text(json.dumps({"schema_version": 99, "entries": []}), encoding="utf-8")
    assert trajectory._read(path) is None


def test_record_treats_non_list_entries_as_fresh_attempt(tmp_path):
    repo = _repo(tmp_path)
    path = trajectory._path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Valid JSON and correct schema_version, but entries is a string instead of a list.
    # The isinstance guard at trajectory.py:109 must prevent list("string") from running.
    path.write_text(
        '{"schema_version": 1, "command": "pytest -q", "updated_at": 1000.0,'
        ' "entries": "not-a-list"}\n',
        encoding="utf-8",
    )
    fresh = trajectory.record(repo, "pytest -q", -2.0, set(), passed=False)
    assert len(fresh) == 1  # non-list entries treated as absent -> fresh attempt


def test_trajectory_path_git_sets_terminal_prompt_env(tmp_path):
    # _path's `git rev-parse --git-dir` must pass GIT_TERMINAL_PROMPT=0 so a
    # headless `looptight verify --patience` cannot block on a credential prompt.
    from unittest.mock import patch

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, str(tmp_path / ".git"), "")

    with patch.object(trajectory.subprocess, "run", fake_run):
        trajectory._path(tmp_path)
    assert captured.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0"


def test_trajectory_path_returns_none_on_oserror(tmp_path):
    # trajectory.py:29 — _path's subprocess.run must catch OSError so
    # trajectory.record() (and verify --patience) degrades gracefully when
    # git is absent from PATH instead of crashing with FileNotFoundError.
    from unittest.mock import patch

    with patch.object(trajectory.subprocess, "run", side_effect=OSError("git not found")):
        result = trajectory._path(tmp_path)
    assert result is None
