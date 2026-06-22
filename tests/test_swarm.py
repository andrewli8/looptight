"""Deterministic swarm manager tests; no provider or network calls."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from looptight import swarm
from looptight.adapters.base import Adapter, run_command
from looptight.cli import build_parser, main
from looptight.config import Config
from looptight.swarm import (
    MAX_WORKERS,
    PlanningResult,
    SwarmResult,
    Worker,
    plan_next_tasks,
    run_continuous_swarm,
    run_swarm,
)
from looptight.tasks import NextResult
from looptight.types import IterationResult


class EditingAdapter(Adapter):
    name = "fake"

    def is_available(self) -> bool:
        return True

    def run_iteration(self, goal, context, workdir, model=None):
        source = "a" if "a.py" in goal else "b"
        (workdir / "src" / f"{source}.py").write_text(goal, encoding="utf-8")
        return IterationResult(transcript="done")


class UnrelatedEditingAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        result = super().run_iteration(goal, context, workdir, model)
        (workdir / "unrelated.txt").write_text("outside task scope", encoding="utf-8")
        return result


class CrashingAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        raise RuntimeError("provider crashed")


class InterruptingAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        raise KeyboardInterrupt


class TimingOutAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        marker = workdir / "orphaned-provider-child"
        proc = run_command(
            ["sh", "-c", f"(sleep 0.2; touch {marker}) & wait"],
            workdir,
            timeout_s=self.worker_timeout_s,
        )
        return IterationResult(
            transcript=proc.stderr,
            ok=False,
            error=proc.stderr.strip(),
        )


class OutOfOrderAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        if "a.py" in goal:
            time.sleep(0.15)
        return super().run_iteration(goal, context, workdir, model)


class PlanningAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        (workdir / "docs" / "STATUS.md").write_text(
            "# Status\n\n## Next\n\n"
            "1. Cover the source task. Evidence: src/a.py:1; "
            "Acceptance: a regression test passes.\n",
            encoding="utf-8",
        )
        return IterationResult(transcript="planned")


class SelfReferentialPlanningAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        (workdir / "docs" / "STATUS.md").write_text(
            "# Status\n\n## Next\n\n"
            "1. Keep planning. Evidence: docs/STATUS.md:1; "
            "Acceptance: another task exists.\n",
            encoding="utf-8",
        )
        return IterationResult(transcript="planned")


class CommittingPlanningAdapter(PlanningAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        result = super().run_iteration(goal, context, workdir, model)
        _git(workdir, "add", "docs/STATUS.md")
        _git(workdir, "commit", "-qm", "provider committed plan")
        return result


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


def test_swarm_parser_accepts_explicit_continuous_rounds():
    args = build_parser().parse_args(
        ["swarm", "--headless", "--continuous", "--max-rounds", "7"]
    )

    assert args.continuous is True
    assert args.max_rounds == 7


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
    assert "task a" in (tmp_path / "src" / "a.py").read_text(encoding="utf-8")
    assert "task b" in (tmp_path / "src" / "b.py").read_text(encoding="utf-8")
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout


def test_swarm_rejects_worker_changes_outside_claimed_task_scope(tmp_path, monkeypatch):
    _repo(tmp_path)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    monkeypatch.setattr(
        "looptight.swarm.get_adapter", lambda name: UnrelatedEditingAdapter()
    )

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
    )

    assert result.workers[0].status == "failed"
    assert result.workers[0].error == "worker changed files outside task scope: unrelated.txt"
    assert result.workers[0].worktree.is_dir()
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=result.workers[0].worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == base
    assert not (tmp_path / "unrelated.txt").exists()


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


def test_swarm_human_output_ends_with_outcome_tally(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    exit_code = main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "2"]
    )

    assert exit_code == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "2 workers · merged 2"


def test_swarm_prints_start_banner_in_human_mode_but_not_json(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "2"]
    ) == 0
    human = capsys.readouterr().out
    assert "swarm · 2 workers · agent codex · verify exit 0 · single round" in human

    # The human run merged worker changes, erasing the fixture's task markers;
    # restore the original commit so the JSON run starts from the same state.
    _git(tmp_path, "reset", "--hard", base)
    assert main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--json"]
    ) == 0
    assert "swarm ·" not in capsys.readouterr().out


def test_swarm_banner_describes_continuous_round_plan():
    assert swarm._swarm_banner(3, "codex", "exit 0", True, 5) == (
        "swarm · 3 workers · agent codex · verify exit 0 · continuous · max 5 rounds"
    )


def test_swarm_tally_counts_each_terminal_status_once():
    workers = [
        Worker(1, {"id": "a"}, "b1", Path("w1"), "base", status="merged"),
        Worker(2, {"id": "b"}, "b2", Path("w2"), "base", status="failed"),
        Worker(3, {"id": "c"}, "b3", Path("w3"), "base", status="merged"),
        Worker(4, {"id": "d"}, "b4", Path("w4"), "base", status="timeout"),
    ]

    assert swarm._swarm_tally(workers) == "4 workers · merged 2 · failed 1 · timeout 1"


def test_swarm_json_output_omits_tally(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    exit_code = main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--json"]
    )

    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    assert "workers ·" not in out
    json.loads(out)


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


def test_swarm_interrupt_stops_processes_and_publishes_terminal_state(tmp_path, monkeypatch):
    _repo(tmp_path)
    stopped = []
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: InterruptingAdapter())
    monkeypatch.setattr("looptight.swarm.stop_active_processes", lambda: stopped.append(True))

    with pytest.raises(KeyboardInterrupt):
        run_swarm(
            tmp_path,
            agent="fake",
            config=Config(verify="exit 0", max_iterations=1),
            workers=1,
        )

    assert stopped == [True]
    state = json.loads((tmp_path / ".git" / "looptight" / "swarm-state.json").read_text())
    assert state["manager"]["status"] == "interrupted"
    assert [worker["status"] for worker in state["workers"]] == ["interrupted"]


def test_swarm_worker_timeout_stops_provider_tree_and_retains_worktree(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: TimingOutAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
        worker_timeout=0.02,
    )

    worker = result.workers[0]
    assert worker.status == "timeout"
    assert worker.error == "provider timed out after 0.02s"
    assert worker.worktree.is_dir()
    time.sleep(0.35)
    assert not (worker.worktree / "orphaned-provider-child").exists()


def test_swarm_publishes_versioned_orchestration_state(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=2,
    )

    state = json.loads((tmp_path / ".git" / "looptight" / "swarm-state.json").read_text())
    assert state["schema_version"] == 1
    assert state["manager"]["status"] == result.status
    assert {task["id"] for task in state["tasks"]} == {
        worker.task["id"] for worker in result.workers
    }
    assert [worker["status"] for worker in state["workers"]] == ["merged", "merged"]


def test_swarm_publishes_worker_results_in_completion_order(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: OutOfOrderAdapter())
    snapshots = []
    publish = swarm._publish_state

    def capture(root, workers, manager_status):
        snapshots.append([worker.status for worker in workers])
        publish(root, workers, manager_status)

    monkeypatch.setattr("looptight.swarm._publish_state", capture)

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=2,
    )

    assert result.passed
    assert ["ready", "ready"] in snapshots
    assert ["running", "running"] in snapshots
    assert ["running", "verified"] in snapshots
    assert [worker.number for worker in result.workers] == [1, 2]


def test_planner_merges_only_grounded_status_tasks(tmp_path, monkeypatch):
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "status")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result == PlanningResult("planned")
    status = (tmp_path / "docs" / "STATUS.md").read_text(encoding="utf-8")
    assert "Evidence: src/a.py:1" in status
    assert "Acceptance: a regression test passes" in status
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout


def test_planner_rejects_self_referential_evidence_and_retains_worktree(
    tmp_path, monkeypatch
):
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "status")
    monkeypatch.setattr(
        "looptight.swarm.get_adapter", lambda name: SelfReferentialPlanningAdapter()
    )

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "valid Evidence paths" in (result.error or "")
    assert result.worktree is not None and result.worktree.is_dir()
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout


def test_planner_accepts_provider_committed_status_change(tmp_path, monkeypatch):
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "status")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: CommittingPlanningAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result == PlanningResult("planned")
    assert "Cover the source task" in (tmp_path / "docs" / "STATUS.md").read_text()


def test_continuous_swarm_replans_and_repeats_rounds(tmp_path, monkeypatch):
    worker = Worker(
        1,
        {"id": "task-1", "source": "status-next", "goal": "do", "location": None},
        "branch",
        tmp_path / "worker",
        "base",
        status="merged",
    )
    rounds = iter([SwarmResult(()), SwarmResult((worker,)), SwarmResult(())])
    planning = iter([PlanningResult("planned"), PlanningResult("no_work")])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *args, **kwargs: next(rounds))
    monkeypatch.setattr(
        "looptight.swarm.plan_next_tasks", lambda *args, **kwargs: next(planning)
    )

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=2,
    )

    assert result.passed
    assert result.workers == (worker,)
    assert result.rounds == 3
    assert result.plans == 1


def test_continuous_swarm_no_ideas_stops_instead_of_planning(tmp_path, monkeypatch):
    planned: list[bool] = []
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult(()))
    monkeypatch.setattr(
        "looptight.swarm.plan_next_tasks",
        lambda *a, **k: planned.append(True) or PlanningResult("planned"),
    )

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        generate_ideas=False,
    )

    assert result.status == "no_work"
    assert planned == []  # planner subagent never invoked when idea generation is off


def _limited_worker(retry: str = "; retry after 5s") -> Worker:
    return Worker(
        1,
        {"id": "task-1", "source": "status-next", "goal": "do", "location": None},
        "branch",
        Path("worker"),
        "base",
        status="limited",
        error="provider rate limit reached" + retry,
    )


def _merged_worker() -> Worker:
    return Worker(
        1,
        {"id": "task-1", "source": "status-next", "goal": "do", "location": None},
        "branch",
        Path("worker"),
        "base",
        status="merged",
    )


def test_continuous_swarm_waits_out_provider_limit_and_resumes(tmp_path, monkeypatch):
    rounds = iter([SwarmResult((_limited_worker(),)), SwarmResult((_merged_worker(),)), SwarmResult(())])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: next(rounds))
    monkeypatch.setattr("looptight.swarm.plan_next_tasks", lambda *a, **k: PlanningResult("no_work"))
    waits: list[float] = []

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        sleep=waits.append,
    )

    assert result.passed
    assert result.resumes == 1
    assert result.workers == (_merged_worker(),)  # the stale limited worker is not retained
    assert waits == [5.0]  # honored the provider's named reset interval


def test_continuous_swarm_limit_is_terminal_without_resume(tmp_path, monkeypatch):
    rounds = iter([SwarmResult((_limited_worker(),))])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: next(rounds))

    result = run_continuous_swarm(tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1)

    assert not result.passed
    assert result.resumes == 0
    assert result.rounds == 1


def test_continuous_swarm_stops_on_genuine_failure_after_resuming(tmp_path, monkeypatch):
    failed = Worker(
        1,
        {"id": "task-1", "source": "status-next", "goal": "do", "location": None},
        "branch",
        Path("worker"),
        "base",
        status="failed",
        error="integration verify: fail",
    )
    rounds = iter([SwarmResult((_limited_worker(),)), SwarmResult((failed,))])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: next(rounds))
    waits: list[float] = []

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        sleep=waits.append,
    )

    assert not result.passed
    assert result.resumes == 1
    assert result.rounds == 2
    assert failed in result.workers


def test_continuous_swarm_caps_a_single_limit_wait(tmp_path, monkeypatch):
    rounds = iter([SwarmResult((_limited_worker("; retry after 99999s"),)), SwarmResult(())])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: next(rounds))
    monkeypatch.setattr("looptight.swarm.plan_next_tasks", lambda *a, **k: PlanningResult("no_work"))
    waits: list[float] = []

    run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        limit_max_wait_seconds=600.0,
        sleep=waits.append,
    )

    assert waits == [600.0]  # a multi-hour reset is clamped; the loop re-polls instead


def test_continuous_swarm_stops_after_max_limit_resumes(tmp_path, monkeypatch):
    # A perpetual limit signal must not loop forever once a cap is set.
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult((_limited_worker("; retry after 1s"),)))
    waits: list[float] = []

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        limit_max_resumes=2,
        sleep=waits.append,
    )

    assert result.status == "error"
    assert "limit" in (result.error or "").lower()
    assert result.resumes == 2  # capped; did not loop indefinitely


def test_continuous_swarm_backs_off_when_no_reset_named(tmp_path, monkeypatch):
    rounds = iter(
        [SwarmResult((_limited_worker(retry=""),)), SwarmResult((_limited_worker(retry=""),)), SwarmResult(())]
    )
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: next(rounds))
    monkeypatch.setattr("looptight.swarm.plan_next_tasks", lambda *a, **k: PlanningResult("no_work"))
    waits: list[float] = []

    run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        limit_backoff_seconds=10.0,
        sleep=waits.append,
    )

    assert waits == [10.0, 20.0]  # exponential back-off across consecutive limited rounds


def test_continuous_swarm_resumes_on_planner_limit(tmp_path, monkeypatch):
    planning = iter([PlanningResult("failed", "provider rate limit reached; retry after 7s"), PlanningResult("no_work")])
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult(()))
    monkeypatch.setattr("looptight.swarm.plan_next_tasks", lambda *a, **k: next(planning))
    waits: list[float] = []

    result = run_continuous_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0"),
        workers=1,
        resume_on_limit=True,
        sleep=waits.append,
    )

    assert result.resumes == 1
    assert waits == [7.0]


def test_swarm_parser_accepts_resume_on_limit_flags():
    args = build_parser().parse_args(
        [
            "swarm",
            "--headless",
            "--continuous",
            "--resume-on-limit",
            "--limit-backoff-seconds",
            "15",
            "--limit-max-wait-seconds",
            "120",
        ]
    )
    assert args.resume_on_limit is True
    assert args.limit_backoff_seconds == 15.0
    assert args.limit_max_wait_seconds == 120.0


def test_swarm_banner_notes_resume_on_limit():
    assert swarm._swarm_banner(2, "claude", "exit 0", True, 0, True) == (
        "swarm · 2 workers · agent claude · verify exit 0 · continuous · max 0 rounds · resume-on-limit"
    )
