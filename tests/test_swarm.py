"""Deterministic swarm manager tests; no provider or network calls."""

from __future__ import annotations

import subprocess
from pathlib import Path

from looptight import swarm
from looptight.adapters.base import Adapter
from looptight.cli import main
from looptight.config import Config
from looptight.swarm import MAX_WORKERS, run_swarm
from looptight.tasks import NextResult
from looptight.types import IterationResult


class EditingAdapter(Adapter):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def run_iteration(self, goal, context, workdir, model=None):
        source = "a" if "a.py" in goal else "b"
        (workdir / f"worker-{source}.txt").write_text(goal, encoding="utf-8")
        return IterationResult(transcript="done")


class CrashingAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        raise RuntimeError("provider crashed")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Looptight Test")
    _git(root, "config", "user.email", "test@looptight.dev")
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("# TODO: task a\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("# TODO: task b\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")


def test_swarm_requires_explicit_headless(capsys):
    assert main(["swarm", "--agent", "codex"]) == 2
    assert "--headless" in capsys.readouterr().out


def test_swarm_rejects_more_than_fifty_workers(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["swarm", "--headless", "--agent", "codex", "--workers", "51"]) == 2
    assert str(MAX_WORKERS) in capsys.readouterr().out


def test_swarm_refuses_dirty_invoking_worktree(tmp_path):
    _repo(tmp_path)
    (tmp_path / "uncommitted.txt").write_text("unsafe", encoding="utf-8")

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=2,
    )

    assert result.error == "swarm requires a clean Git worktree"
    assert result.workers == ()


def test_swarm_runs_isolated_workers_and_serializes_verified_merges(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=2,
    )

    assert result.passed
    assert [worker.status for worker in result.workers] == ["merged", "merged"]
    assert len({worker.task["id"] for worker in result.workers}) == 2
    assert (tmp_path / "worker-a.txt").is_file()
    assert (tmp_path / "worker-b.txt").is_file()
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout


def test_swarm_cleans_unstarted_worktree_when_preparation_fails(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    real_next_task = swarm.next_task
    calls = {"count": 0}

    def flaky_next_task(workdir):
        calls["count"] += 1
        if calls["count"] == 2:
            return NextResult(status="error", error="claim broke")
        return real_next_task(workdir)

    monkeypatch.setattr("looptight.swarm.next_task", flaky_next_task)

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=2,
    )

    assert result.error == "claim broke"
    listing = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert "detached" not in listing


def test_swarm_contains_worker_runtime_exception(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: CrashingAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
    )

    assert not result.passed
    assert result.workers[0].status == "failed"
    assert result.workers[0].error == "worker crashed: provider crashed"
