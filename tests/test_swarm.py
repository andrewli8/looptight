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


class NoOpAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        return IterationResult(transcript="did nothing")  # success, but no file changes


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
            returncode=proc.returncode,
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


def test_swarm_refuses_direct_push_when_policy_disables_it(
    tmp_path, monkeypatch, capsys
):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".looptight.toml").write_text(
        'verify = "exit 0"\nno_direct_push = true\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: pytest.fail("ran swarm"))

    assert main(["swarm", "--headless", "--agent", "codex", "--push"]) == 2

    assert "direct push disabled by policy" in capsys.readouterr().out


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


class WholeFileRewriteAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        # Rewrite the whole shared file with this worker's goal → conflicting content
        # across workers, forcing a merge conflict on the serialized integration.
        (workdir / "src" / "a.py").write_text(f"# done: {goal}\n", encoding="utf-8")
        return IterationResult(transcript="done")


def test_swarm_cli_prints_error_and_no_work_results(tmp_path, monkeypatch, capsys):
    # The human swarm output surfaces a top-level error and a NO_WORK result.
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult((), "boom"))
    main(["swarm", "--headless", "--agent", "codex", "--verify", "exit 0"])
    out = capsys.readouterr().out
    assert "swarm error:" in out and "boom" in out

    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult(()))
    assert main(["swarm", "--headless", "--agent", "codex", "--verify", "exit 0"]) == 0
    assert "NO_WORK" in capsys.readouterr().out


def test_swarm_marks_a_conflicting_worker_as_conflict(tmp_path, monkeypatch):
    # Two workers whose verified branches both rewrite the same file conflict on the
    # serialized merge: the first integrates, the second aborts and is marked "conflict"
    # (retained for recovery), never producing a broken merge or a dirty base tree.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Looptight Test")
    _git(tmp_path, "config", "user.email", "test@looptight.dev")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "# TODO: task one in a.py\n# TODO: task two in a.py\n", encoding="utf-8"
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "fixture")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: WholeFileRewriteAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=2,
    )

    assert sorted(w.status for w in result.workers) == ["conflict", "merged"]
    conflicted = next(w for w in result.workers if w.status == "conflict")
    assert conflicted.worktree.exists()  # retained for recovery
    # The base tree is left coherent (the aborted merge did not dirty it).
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout


def test_swarm_rejects_a_worker_that_produces_no_changes(tmp_path, monkeypatch):
    # A worker whose run loop succeeds but makes no file changes (HEAD still at base) is a
    # no-op, not a success: it is marked failed rather than merged as an empty result.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: NoOpAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
    )

    assert not result.passed
    assert result.workers[0].status == "failed"
    assert result.workers[0].error == "agent produced no changes"


def test_swarm_does_not_merge_work_that_fails_verify(tmp_path, monkeypatch):
    # The swarm's core safety guarantee: a worker whose verify fails is not merged. With a
    # verify that always fails, every worker's run loop ends non-success → failed, the base
    # repo is untouched, and the failed worktrees are retained for inspection.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 1", max_iterations=1),
        workers=2,
    )

    assert not result.passed
    assert result.status == "fail"
    assert [w.status for w in result.workers] == ["failed", "failed"]
    # Not merged: the base repo still holds the original TODO, not the goal the worker wrote.
    assert (tmp_path / "src" / "a.py").read_text(encoding="utf-8") == "# TODO: task a\n"
    # The base worktree is clean and the failed worktrees are retained for inspection.
    assert not subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert all(w.worktree.exists() for w in result.workers)


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
    assert list((tmp_path / ".git" / "looptight" / "swarm").iterdir()) == []


def test_swarm_no_work_removes_empty_run_directory(tmp_path, monkeypatch):
    _repo(tmp_path)
    (tmp_path / "src" / "a.py").write_text("# complete\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# complete\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "complete tasks")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
    )

    assert result.status == "no_work"
    assert list((tmp_path / ".git" / "looptight" / "swarm").iterdir()) == []


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


def test_swarm_human_output_explains_integration_and_next_action(
    tmp_path, monkeypatch, capsys
):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    assert main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "1"]
    ) == 0

    out = capsys.readouterr().out
    assert "explanation: verified workers integrate one at a time" in out
    assert "integration: merged 1" in out
    assert "next: inspect retained worktrees for failures or continue with `looptight next --json`" in out
    assert out.splitlines()[-1] == "1 workers · merged 1"


def test_swarm_human_output_explains_recovery_guarantees(
    tmp_path, monkeypatch, capsys
):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    assert main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "1"]
    ) == 0

    out = capsys.readouterr().out
    assert "recovery: stale leases requeue when abandoned runs are reaped" in out
    assert "recovery: pending integrations are reconciled before claiming new work" in out
    assert "recovery: rejected pushes stay failed and are never force-pushed" in out


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

    def flaky_next_task(workdir, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            return NextResult(status="error", error="claim broke")
        return real_next_task(workdir, **kwargs)

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
    # One worker finishes and is published as "verified" while the other is
    # still "running": state is published per completion, not once at the end.
    # Which worker wins the race is thread-scheduling dependent, so assert the
    # partial snapshot order-independently.
    assert any(sorted(snapshot) == ["running", "verified"] for snapshot in snapshots)
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


def test_planned_tasks_grounded_tolerates_backticked_evidence(tmp_path):
    # The planner's grounding check must accept a markdown-backticked evidence
    # anchor (``Evidence: `src/a.py:1` ``), the idiomatic form an LLM planner
    # emits. Otherwise every backticked task is rejected as ungrounded — the
    # same defect the discovery grounding gate had.
    from looptight.discovery import Candidate
    from looptight.swarm import _planned_tasks_are_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    grounded = Candidate(
        title="t", source="status-next", location="docs/STATUS.md:5",
        suggested_verify=None, score=0.0,
        detail="Fix it. Evidence: `src/a.py:1` Acceptance: ok", acceptance="ok",
    )
    assert _planned_tasks_are_grounded(tmp_path, [grounded]) is True
    # A backticked but fabricated path is still rejected.
    fabricated = Candidate(
        title="t", source="status-next", location="docs/STATUS.md:6",
        suggested_verify=None, score=0.0,
        detail="Do it. Evidence: `src/ghost.py:1` Acceptance: ok", acceptance="ok",
    )
    assert _planned_tasks_are_grounded(tmp_path, [fabricated]) is False


def test_planned_tasks_grounded_rejection_branches(tmp_path):
    # The planner grounding gate's three remaining rejection/acceptance branches:
    # no evidence anchor, path-only evidence (no :line), and a line past the file end.
    from looptight.discovery import Candidate
    from looptight.swarm import _planned_tasks_are_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n" * 5, encoding="utf-8")  # 5 lines

    def _c(detail):
        return Candidate(
            title="t", source="status-next", location="docs/STATUS.md:5",
            suggested_verify=None, score=0.0, detail=detail, acceptance="ok",
        )

    # No evidence anchor at all → not grounded.
    assert _planned_tasks_are_grounded(tmp_path, [_c("Fix it. Acceptance: ok")]) is False
    # Path-only evidence (no :line) to a real file → grounded.
    assert _planned_tasks_are_grounded(tmp_path, [_c("Fix it. Evidence: `src/a.py`")]) is True
    # A cited line beyond the file's length → not grounded.
    assert _planned_tasks_are_grounded(tmp_path, [_c("Fix it. Evidence: `src/a.py:999`")]) is False


def test_task_paths_resolves_backticked_evidence_to_bare_path(tmp_path):
    # The change-scope set must include the file a backticked evidence anchor
    # points at; otherwise a worker's edit to its own evidence file looks
    # out-of-scope. `_summary_and_evidence` now emits backticked anchors.
    from looptight.swarm import _task_paths

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    paths = _task_paths(tmp_path, {"location": "docs/STATUS.md:5", "evidence": "Evidence: `src/a.py:1`"})
    assert "src/a.py" in paths
    assert "`src/a.py:1`" not in paths  # the backticks are not kept as a path


def test_planned_tasks_grounded_tolerates_bold_evidence_marker(tmp_path):
    # The planner check must share the gate's marker tolerance: a bold marker
    # (``**Evidence:** `path` ``) should still ground, not be rejected because a
    # divergent regex missed it.
    from looptight.discovery import Candidate
    from looptight.swarm import _planned_tasks_are_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n" * 5, encoding="utf-8")
    candidate = Candidate(
        title="t", source="status-next", location="docs/STATUS.md:5",
        suggested_verify=None, score=0.0,
        detail="Fix it. **Evidence:** `src/a.py:1` Acceptance: ok", acceptance="ok",
    )
    assert _planned_tasks_are_grounded(tmp_path, [candidate]) is True


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
        "swarm · 2 workers · agent claude · verify exit 0 · continuous · unbounded rounds · resume-on-limit"
    )


def test_swarm_banner_renders_unbounded_for_zero_max_rounds():
    # max_rounds == 0 is "until no work/failure/interruption" (unbounded), so the
    # banner must not assert a "max 0 rounds" cap on the default continuous run.
    banner = swarm._swarm_banner(4, "claude", "pytest -q", True, 0)
    assert "unbounded rounds" in banner
    assert "max 0 rounds" not in banner


def test_swarm_reconciles_crashed_integration_on_start(tmp_path, monkeypatch):
    from looptight.coordinator import Coordinator
    from looptight.integration_queue import InjectedCrash, Integrator

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), "-c", "user.name=T", "-c", "user.email=t@t.test", *args],
            capture_output=True, text=True, check=True,
        )

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "readme.md").write_text("hi\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    git("checkout", "-q", "-b", "cand")
    (tmp_path / "feature.txt").write_text("x\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "feature")
    candidate = git("rev-parse", "HEAD").stdout.strip()
    git("checkout", "-q", "main")

    db = Coordinator.open(tmp_path)
    run = db.start_run("worker")
    lease = db.claim([{"id": "t1"}], run.id, ttl_s=60)
    integration_id = db.enqueue_integration(lease, "refs/heads/main", candidate)
    with pytest.raises(InjectedCrash):
        Integrator(db, crash_after="after_commit").run_next(tmp_path, "exit 0")
    assert db.integration(integration_id).state == "integrating"
    db.close()

    # No grounded tasks, so the round claims nothing — but it must reconcile first.
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    run_swarm(tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1)

    after = Coordinator.open(tmp_path)
    assert after.integration(integration_id).state == "complete"
    reachable = git(
        "log", "refs/heads/main", "--pretty=%H", f"--grep=Looptight-Integration-ID: {integration_id}"
    ).stdout.split()
    assert len(reachable) == 1


def test_swarm_push_publishes_via_durable_queue(tmp_path, monkeypatch):
    _repo(tmp_path)
    branch = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    remote = tmp_path.with_name(tmp_path.name + "_remote.git")
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(tmp_path, "remote", "add", "origin", str(remote))
    _git(tmp_path, "push", "-u", "-q", "origin", branch)

    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1, push=True
    )

    assert result.pushed == "pushed"
    local_tip = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", branch], capture_output=True, text=True, check=True
    ).stdout.strip()
    remote_tip = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", branch], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert remote_tip == local_tip  # exact integrated result published to the remote


class RewordedTimeoutAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        # Different wording than base.py, but the timeout exit code is what matters.
        return IterationResult(ok=False, error="the model took too long, sorry", returncode=124)


def test_swarm_classifies_timeout_by_exit_code_not_message(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: RewordedTimeoutAdapter())
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )
    assert result.workers[0].status == "timeout"  # classified by returncode 124, not the string


def test_planner_goal_includes_experience_when_available(tmp_path, monkeypatch):
    from looptight.coordinator import Coordinator

    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "status")

    # Record a failure so the experience model is non-empty.
    coord = Coordinator.open(tmp_path)
    coord.record_failure("idea-z", "lint")
    coord.close()

    captured: dict[str, str] = {}

    class _CapturingPlanningAdapter(PlanningAdapter):
        def run_iteration(self, goal, context, workdir, model=None):
            captured["goal"] = goal
            return super().run_iteration(goal, context, workdir, model)

    monkeypatch.setattr(
        "looptight.swarm.get_adapter", lambda name: _CapturingPlanningAdapter()
    )

    plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert "goal" in captured, "run_iteration was never called"
    assert "Learned from past runs" in captured["goal"]
    assert "idea-z" in captured["goal"]


def test_planner_goal_equals_planning_goal_without_coordinator(tmp_path, monkeypatch):
    from looptight.prompts import PLANNING_GOAL

    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n\n## Next\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "status")

    # No coordinator DB — Coordinator.open should return None outside a git repo
    # with no coordinator. We verify by pointing open at a non-coordinator path.
    captured: dict[str, str] = {}

    class _CapturingPlanningAdapter(PlanningAdapter):
        def run_iteration(self, goal, context, workdir, model=None):
            captured["goal"] = goal
            return super().run_iteration(goal, context, workdir, model)

    monkeypatch.setattr(
        "looptight.swarm.get_adapter", lambda name: _CapturingPlanningAdapter()
    )
    # Stub Coordinator.open to return None (no coordinator available).
    monkeypatch.setattr("looptight.swarm.Coordinator.open", staticmethod(lambda root: None))

    plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert captured.get("goal") == PLANNING_GOAL


def test_continuous_swarm_stops_after_idle_planning_rounds(tmp_path, monkeypatch):
    # Rounds never produce workers and planning always "plans": must stop, not loop.
    monkeypatch.setattr("looptight.swarm.run_swarm", lambda *a, **k: SwarmResult(()))
    monkeypatch.setattr("looptight.swarm.plan_next_tasks", lambda *a, **k: PlanningResult("planned"))

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1
    )

    assert result.status == "error"
    assert "no merged progress" in (result.error or "")
    assert result.rounds <= 5  # bounded, did not loop forever


def test_remove_worker_worktree_force_removes_dir_with_untracked_files(tmp_path):
    # A disposable worker worktree with leftover untracked files must still be
    # removed; plain `git worktree remove` refuses (exit 128) without --force.
    root = tmp_path / "repo"
    root.mkdir()
    _repo(root)
    worktree = tmp_path / "wt" / "w1"
    worktree.parent.mkdir()
    _git(root, "worktree", "add", "-q", "--detach", str(worktree))
    (worktree / "untracked.txt").write_text("leftover", encoding="utf-8")

    result = swarm._remove_worker_worktree(root, worktree)
    assert result.returncode == 0
    assert not worktree.exists()


def test_swarm_git_runs_non_interactively(tmp_path, monkeypatch):
    # swarm._git pushes directly; like the integration helper it must be
    # non-interactive so a credential-needing push fails fast instead of hanging.
    import looptight.swarm as sw

    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(sw.subprocess, "run", fake_run)
    sw._git(tmp_path, "status")
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
