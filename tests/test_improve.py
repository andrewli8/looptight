from __future__ import annotations

import subprocess
from pathlib import Path

from looptight.improve import ImproveStopReason, _audit_goal, _commit_subject, run_improve
from looptight.propose import Candidate
from looptight.types import RunResult, StopReason


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _init_repo(path: Path) -> None:
    assert _git(["init", "-q"], path).returncode == 0
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "Test"], path)
    (path / "app.py").write_text("old\n")
    _git(["add", "app.py"], path)
    assert _git(["commit", "-q", "-m", "initial"], path).returncode == 0


def _result(
    reason: StopReason = StopReason.SUCCESS,
    *,
    cost: float = 0.5,
    error: str | None = None,
) -> RunResult:
    return RunResult(
        goal="task",
        agent="fake",
        mode="supply",
        stop_reason=reason,
        total_cost_usd=cost,
        error=error,
    )


def _candidate() -> Candidate:
    return Candidate(
        title="fix concrete bug",
        source="todo",
        location="app.py:1",
        suggested_verify="pytest -q",
        score=20.0,
    )


def test_audit_prompt_requires_noop_audits_to_leave_tree_unchanged():
    goal = _audit_goal(3, ["no changes from audit #2"])

    assert "REVIEW-QUEUE.md" in goal
    assert "STATUS" in goal
    assert "other documentation" in goal
    assert "merely to report" in goal
    assert "leave the working tree unchanged" in goal.lower()
    assert "no evidence-backed improvement" in goal.lower()


def test_audit_prompt_allows_product_documentation_as_the_improvement():
    goal = _audit_goal(1, [])

    assert "legitimate product documentation" in goal.lower()
    assert "actual evidence-backed improvement" in goal.lower()


def test_commit_subject_truncates_at_word_boundary():
    # A hard character slice cut subjects mid-word (e.g. "...then a seco").
    # Truncate on a word boundary so the subject ends on a whole word.
    title = (
        "Record the flagship gif: the same command across agents, then a second "
        "task that benefits from a lesson"
    )
    subject = _commit_subject(
        Candidate(title=title, source="status-next", location="docs/STATUS.md",
                  suggested_verify=None, score=0.0),
        1,
    )
    assert subject.startswith("chore: ")
    body = subject[len("chore: "):]
    assert title.startswith(body)  # a clean prefix of the title
    assert len(body) <= 68
    # the character right after the kept prefix is a space → no mid-word cut
    assert title[len(body)] == " "


def test_refuses_to_start_with_dirty_tree(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("dirty\n")

    result = run_improve(tmp_path, lambda goal, cp: _result())

    assert result.stop_reason is ImproveStopReason.GIT_ERROR
    assert result.tasks_attempted == 0
    assert "clean" in (result.error or "").lower()


def test_zero_session_budget_stops_before_first_task(tmp_path):
    _init_repo(tmp_path)

    def must_not_run(goal, checkpointer):
        raise AssertionError("task ran with no session budget")

    result = run_improve(tmp_path, must_not_run, session_budget_usd=0)

    assert result.stop_reason is ImproveStopReason.SESSION_BUDGET
    assert result.tasks_attempted == 0


def test_moves_from_grounded_candidate_to_audit_without_stopping(tmp_path):
    _init_repo(tmp_path)
    goals: list[str] = []

    def run_task(goal, checkpointer):
        goals.append(goal)
        return _result(cost=0.5)

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [_candidate()],
        session_budget_usd=1.0,
    )

    assert result.stop_reason is ImproveStopReason.SESSION_BUDGET
    assert result.tasks_attempted == 2
    assert "fix concrete bug" in goals[0]
    assert "audit" in goals[1].lower()


def test_verified_change_is_committed_and_optionally_pushed(tmp_path):
    _init_repo(tmp_path)
    commands: list[list[str]] = []

    def run_task(goal, checkpointer):
        (tmp_path / "app.py").write_text("new\n")
        return _result(cost=1.0)

    def git_fn(args, cwd):
        commands.append(args)
        if args == ["push"]:
            return subprocess.CompletedProcess(["git", "push"], 0, "", "")
        return _git(args, cwd)

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [_candidate()],
        session_budget_usd=1.0,
        push=True,
        git_fn=git_fn,
    )

    assert result.commits == 1
    assert ["push"] in commands
    assert _git(["status", "--porcelain"], tmp_path).stdout == ""
    assert "fix concrete bug" in _git(["log", "-1", "--pretty=%s"], tmp_path).stdout


def test_provider_error_stops_continuous_session(tmp_path):
    _init_repo(tmp_path)

    result = run_improve(
        tmp_path,
        lambda goal, cp: _result(StopReason.ERROR, error="usage limit reached"),
        propose_fn=lambda root, limit=0: [],
    )

    assert result.stop_reason is ImproveStopReason.PROVIDER_STOP
    assert result.error == "usage limit reached"


def test_unavailable_provider_stops_instead_of_retrying_forever(tmp_path):
    _init_repo(tmp_path)

    result = run_improve(
        tmp_path,
        lambda goal, cp: _result(StopReason.AGENT_UNAVAILABLE),
        propose_fn=lambda root, limit=0: [],
    )

    assert result.stop_reason is ImproveStopReason.PROVIDER_STOP
    assert result.tasks_attempted == 1


def test_failed_task_is_rolled_back_before_continuing(tmp_path):
    _init_repo(tmp_path)
    calls = 0

    def run_task(goal, checkpointer):
        nonlocal calls
        calls += 1
        if calls == 1:
            (tmp_path / "app.py").write_text("broken\n")
            (tmp_path / "created.py").write_text("remove me\n")
            return _result(StopReason.ITERATION_CAP)
        assert (tmp_path / "app.py").read_text() == "old\n"
        assert not (tmp_path / "created.py").exists()
        return _result(StopReason.ERROR, error="provider stopped")

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [],
    )

    assert calls == 2
    assert result.stop_reason is ImproveStopReason.PROVIDER_STOP
    assert _git(["status", "--porcelain"], tmp_path).stdout == ""


def test_commit_failure_stops_session(tmp_path):
    _init_repo(tmp_path)

    def run_task(goal, checkpointer):
        (tmp_path / "app.py").write_text("new\n")
        (tmp_path / "created.py").write_text("new file\n")
        return _result()

    def git_fn(args, cwd):
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(["git", *args], 1, "", "commit failed")
        return _git(args, cwd)

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [_candidate()],
        git_fn=git_fn,
    )

    assert result.stop_reason is ImproveStopReason.GIT_ERROR
    assert "commit" in (result.error or "")
    assert _git(["status", "--porcelain"], tmp_path).stdout == ""
    assert not (tmp_path / "created.py").exists()


def test_status_failure_after_task_rolls_back_changes(tmp_path):
    _init_repo(tmp_path)
    status_calls = 0

    def run_task(goal, checkpointer):
        (tmp_path / "app.py").write_text("new\n")
        (tmp_path / "created.py").write_text("new file\n")
        return _result()

    def git_fn(args, cwd):
        nonlocal status_calls
        if args == ["status", "--porcelain"]:
            status_calls += 1
            if status_calls == 2:
                return subprocess.CompletedProcess(["git", *args], 1, "", "status failed")
        return _git(args, cwd)

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [_candidate()],
        git_fn=git_fn,
    )

    assert result.stop_reason is ImproveStopReason.GIT_ERROR
    assert result.error == "status failed"
    assert (tmp_path / "app.py").read_text() == "old\n"
    assert not (tmp_path / "created.py").exists()
    assert _git(["status", "--porcelain"], tmp_path).stdout == ""


def test_keyboard_interrupt_stops_cleanly(tmp_path):
    _init_repo(tmp_path)

    def interrupt(goal, checkpointer):
        raise KeyboardInterrupt

    result = run_improve(
        tmp_path,
        interrupt,
        propose_fn=lambda root, limit=0: [],
    )

    assert result.stop_reason is ImproveStopReason.INTERRUPTED
    assert result.tasks_attempted == 0


def test_task_runner_exception_rolls_back_before_stopping(tmp_path):
    _init_repo(tmp_path)

    def crash(goal, checkpointer):
        (tmp_path / "app.py").write_text("partial edit\n")
        (tmp_path / "created.py").write_text("partial file\n")
        raise RuntimeError("agent integration crashed")

    result = run_improve(
        tmp_path,
        crash,
        propose_fn=lambda root, limit=0: [],
    )

    assert result.stop_reason is ImproveStopReason.PROVIDER_STOP
    assert result.tasks_attempted == 0
    assert result.error == "task runner failed: RuntimeError: agent integration crashed"
    assert (tmp_path / "app.py").read_text() == "old\n"
    assert not (tmp_path / "created.py").exists()
    assert _git(["status", "--porcelain"], tmp_path).stdout == ""


def test_stops_after_consecutive_idle_tasks_without_budget(tmp_path):
    # Runaway guard: with no session budget and an agent that keeps passing but
    # changing nothing (cost $0 — e.g. codex/opencode), the loop must stop after
    # a few idle tasks instead of spinning forever burning the provider quota.
    _init_repo(tmp_path)
    calls = 0

    def run_task(goal, checkpointer):
        nonlocal calls
        calls += 1
        return _result(cost=0.0)  # passed, no file changes, no cost

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [],
        session_budget_usd=None,
        max_idle_tasks=3,
    )

    assert result.stop_reason is ImproveStopReason.NO_PROGRESS
    assert result.tasks_attempted == 3
    assert result.commits == 0


def test_idle_streak_resets_on_commit(tmp_path):
    # A committing task resets the idle streak, so intermittent progress keeps
    # the loop alive rather than tripping the no-progress stop prematurely.
    _init_repo(tmp_path)
    calls = 0

    def run_task(goal, checkpointer):
        nonlocal calls
        calls += 1
        if calls == 2:  # only the 2nd task makes a committable change
            (tmp_path / "app.py").write_text("v2\n")
        return _result(cost=0.0)

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [],
        max_idle_tasks=2,
    )

    # idle, commit(reset), idle, idle -> stop on the 4th task (not the 3rd).
    assert result.stop_reason is ImproveStopReason.NO_PROGRESS
    assert result.commits == 1
    assert result.tasks_attempted == 4


def test_max_idle_tasks_zero_disables_the_idle_guard(tmp_path):
    # The runaway guard must be disablable (max_idle_tasks<=0) so the loop can
    # run past the default idle cap; the session budget then bounds it. This
    # pins the escape hatch and the `> 0` guard against regression.
    _init_repo(tmp_path)

    def run_task(goal, checkpointer):
        return _result(cost=0.1)  # passes, makes no change (idle), small cost

    result = run_improve(
        tmp_path,
        run_task,
        propose_fn=lambda root, limit=0: [],
        session_budget_usd=1.0,  # ~10 idle tasks before this trips
        max_idle_tasks=0,  # guard disabled
    )

    assert result.stop_reason is ImproveStopReason.SESSION_BUDGET
    assert result.tasks_attempted >= 4  # ran well past the default cap of 3
