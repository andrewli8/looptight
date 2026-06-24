"""Repo-private goal state for the vision-driven build loop."""

from __future__ import annotations

import subprocess

from looptight.goal import Goal, clear_goal, goal_path, read_goal, write_goal


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_goal_state_round_trips(tmp_path):
    repo = _repo(tmp_path)
    goal = Goal(
        vision="a CLI todo app", done_check="pytest -q",
        continuous=True, max_iterations=10, iteration=3,
    )
    write_goal(repo, goal)
    assert read_goal(repo) == goal


def test_read_goal_absent_is_none(tmp_path):
    assert read_goal(_repo(tmp_path)) is None


def test_clear_goal_removes_state(tmp_path):
    repo = _repo(tmp_path)
    write_goal(repo, Goal(vision="x"))
    assert clear_goal(repo) is True
    assert read_goal(repo) is None
    assert clear_goal(repo) is False  # already gone


def test_goal_state_is_repo_private_and_untracked(tmp_path):
    repo = _repo(tmp_path)
    write_goal(repo, Goal(vision="x"))
    # State lives under the git common dir, so git never tracks it.
    assert (repo / ".git" / "looptight" / "goal.json").is_file()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    )
    assert "goal.json" not in status.stdout


def test_read_goal_ignores_unknown_schema(tmp_path):
    repo = _repo(tmp_path)
    path = goal_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version": 99, "vision": "x"}', encoding="utf-8")
    assert read_goal(repo) is None


def test_goal_next_without_a_goal_reports_no_goal(tmp_path):
    from looptight.goal import goal_next

    assert goal_next(_repo(tmp_path)).status == "no_goal"


def test_goal_next_active_emits_directive_and_bumps_iteration(tmp_path):
    from looptight.goal import goal_next

    repo = _repo(tmp_path)
    write_goal(repo, Goal(vision="a CLI todo app"))
    decision = goal_next(repo, check_runner=lambda root, cmd: False)
    assert decision.status == "active"
    assert "a CLI todo app" in decision.directive["prompt"]
    assert decision.directive["action"] == "build_increment"
    assert decision.iteration == 1
    assert read_goal(repo).iteration == 1  # persisted across calls


def test_goal_next_reports_done_when_check_passes_without_bumping(tmp_path):
    from looptight.goal import goal_next

    repo = _repo(tmp_path)
    write_goal(repo, Goal(vision="x", done_check="pytest -q"))
    decision = goal_next(repo, check_runner=lambda root, cmd: True)
    assert decision.status == "done"
    assert decision.directive is None
    assert read_goal(repo).iteration == 0  # a met goal does not iterate


def test_goal_next_stops_at_max_iterations(tmp_path):
    from looptight.goal import goal_next

    repo = _repo(tmp_path)
    write_goal(repo, Goal(vision="x", max_iterations=1, iteration=1))
    decision = goal_next(repo, check_runner=lambda root, cmd: False)
    assert decision.status == "stop"
    assert decision.reason == "max_iterations"


def test_goal_build_prompt_carries_vision_and_bootstrap():
    from looptight.prompts import goal_build

    text = goal_build("a CLI todo app")
    assert "a CLI todo app" in text
    assert "test" in text.lower()  # bootstrap a verify command when none exists
