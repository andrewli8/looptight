"""Deterministic swarm manager tests; no provider or network calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from looptight.adapters.base import Adapter
from looptight.cli import main
from looptight.config import Config
from looptight.swarm import MAX_WORKERS, SwarmResult, Worker, run_swarm
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


def test_swarm_json_reports_versioned_result(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    exit_code = main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "swarm"
    assert payload["status"] == "pass"
    assert payload["error"] is None
    assert payload["push"] is None
    assert [worker["status"] for worker in payload["workers"]] == ["merged", "merged"]
    assert all(worker["task_id"] for worker in payload["workers"])
    assert all(worker["error"] is None for worker in payload["workers"])
    assert all(worker["worktree"] for worker in payload["workers"])


def test_swarm_result_as_dict_reports_failure_and_paths(tmp_path):
    worktree = tmp_path / "wt"
    worker = Worker(
        number=1,
        task={"id": "t-1", "source": "src", "goal": "do", "location": None},
        branch="b",
        worktree=worktree,
        base="abc",
        status="failed",
        error="boom",
    )
    result = SwarmResult((worker,), error="could not push", pushed="failed")

    payload = result.as_dict()

    assert payload["status"] == "error"
    assert payload["error"] == "could not push"
    assert payload["push"] == "failed"
    assert payload["workers"][0]["task_id"] == "t-1"
    assert payload["workers"][0]["status"] == "failed"
    assert payload["workers"][0]["error"] == "boom"
    assert payload["workers"][0]["worktree"] == str(worktree)


def test_swarm_human_output_prints_retained_worktree_for_failed_worker(
    tmp_path, monkeypatch, capsys
):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: CrashingAdapter())

    exit_code = main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "1"]
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "· failed" in out
    assert "worktree retained for recovery:" in out
    retained = next(
        line.split("worktree retained for recovery:")[1].strip()
        for line in out.splitlines()
        if "worktree retained for recovery:" in line
    )
    assert Path(retained).is_dir()


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
