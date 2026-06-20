"""Swarm provisioning + launch (offline; git and spawn are injected)."""

from __future__ import annotations

import subprocess

import pytest

from looptight.swarm import (
    WORKER_PROMPT,
    plan_swarm,
    swarm_down,
    swarm_up,
)


def _ok(args, cwd):
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


def test_plan_swarm_makes_distinct_isolated_workers(tmp_path):
    specs = plan_swarm(tmp_path / "repo", 3, "claude")

    assert [s.index for s in specs] == [1, 2, 3]
    # Every worker is isolated: distinct worktree, branch, and claim identity.
    assert len({s.worktree for s in specs}) == 3
    assert len({s.branch for s in specs}) == 3
    assert len({s.session_id for s in specs}) == 3
    assert all(s.env["LOOPTIGHT_SESSION_ID"] == s.session_id for s in specs)


def test_plan_swarm_uses_each_agents_cli_and_loop_contract(tmp_path):
    assert plan_swarm(tmp_path, 1, "claude")[0].argv[:2] == ("claude", "-p")
    assert plan_swarm(tmp_path, 1, "codex")[0].argv[:2] == ("codex", "exec")
    assert plan_swarm(tmp_path, 1, "opencode")[0].argv[:2] == ("opencode", "run")

    prompt = plan_swarm(tmp_path, 1, "claude")[0].argv[2]
    assert prompt == WORKER_PROMPT
    assert "looptight next" in prompt
    assert "looptight verify" in prompt
    assert "NO_WORK" in prompt


def test_plan_swarm_rejects_bad_input(tmp_path):
    with pytest.raises(ValueError):
        plan_swarm(tmp_path, 0, "claude")
    with pytest.raises(ValueError):
        plan_swarm(tmp_path, 1, "nope")


def test_swarm_up_creates_one_worktree_and_spawn_per_worker(tmp_path):
    git_calls: list[list[str]] = []
    spawns: list[tuple[list[str], object, dict[str, str]]] = []

    def git_fn(args, cwd):
        git_calls.append(args)
        return _ok(args, cwd)

    def spawn_fn(argv, cwd, env):
        spawns.append((argv, cwd, env))

    result = swarm_up(
        tmp_path / "repo", 2, "codex",
        base_dir=tmp_path / "wt", git_fn=git_fn, spawn_fn=spawn_fn,
    )

    assert len(result.launched) == 2
    assert result.errors == ()
    worktree_adds = [a for a in git_calls if a[:2] == ["worktree", "add"]]
    assert len(worktree_adds) == 2
    # Each worker spawned in its own worktree with a distinct claim identity.
    assert len(spawns) == 2
    assert len({env["LOOPTIGHT_SESSION_ID"] for _, _, env in spawns}) == 2
    assert all(argv[0] == "codex" for argv, _, _ in spawns)


def test_swarm_up_skips_and_records_a_failed_worktree(tmp_path):
    spawns = []

    def git_fn(args, cwd):
        rc = 1 if "w2" in " ".join(args) else 0  # second worktree add fails
        return subprocess.CompletedProcess(["git", *args], rc, "", "already exists")

    result = swarm_up(
        tmp_path, 2, "claude",
        base_dir=tmp_path / "wt", git_fn=git_fn,
        spawn_fn=lambda *a: spawns.append(a),
    )

    assert len(result.launched) == 1  # only the worker that provisioned cleanly
    assert len(result.errors) == 1
    assert "w2" in result.errors[0]
    assert len(spawns) == 1  # the failed worker is never launched


def test_swarm_down_force_removes_worktrees(tmp_path):
    base = tmp_path / "wt"
    (base / "w1").mkdir(parents=True)
    (base / "w2").mkdir(parents=True)
    removed_calls: list[list[str]] = []

    def git_fn(args, cwd):
        removed_calls.append(args)
        return _ok(args, cwd)

    removed = swarm_down(tmp_path, base_dir=base, git_fn=git_fn)

    assert len(removed) == 2
    assert all(a[:3] == ["worktree", "remove", "--force"] for a in removed_calls)


def test_swarm_down_is_a_noop_without_a_swarm(tmp_path):
    assert swarm_down(tmp_path, base_dir=tmp_path / "missing") == []
