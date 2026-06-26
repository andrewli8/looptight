"""Repo-private goal state for the vision-driven build loop."""

from __future__ import annotations

import json
import subprocess

import pytest

from looptight.goal import Goal, clear_goal, goal_path, read_goal, run_done_check, write_goal


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


def test_write_goal_cleans_up_tmp_when_replace_fails(tmp_path, monkeypatch):
    # If the atomic rename fails after the temp file is written, the temp must
    # not be left behind: the error propagates and no stale .tmp remains.
    repo = _repo(tmp_path)
    goal = Goal(vision="x")
    tmp = goal_path(repo).with_suffix(".tmp")

    def boom(src, dst):
        raise OSError("cross-device rename")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)
    with pytest.raises(OSError):
        write_goal(repo, goal)
    assert not tmp.exists()
    assert read_goal(repo) is None  # the goal file was never created


def test_write_goal_raises_outside_git(tmp_path):
    # goal_path returns None outside a Git repo, so write_goal must raise a
    # clear RuntimeError rather than crashing with an AttributeError or OSError.
    with pytest.raises(RuntimeError, match="outside a Git repository"):
        write_goal(tmp_path, Goal(vision="x"))


def test_read_goal_returns_none_on_non_utf8_file(tmp_path):
    # An unreadable (non-UTF-8) goal file must yield None, not raise: the
    # contract promises None when the state is unreadable.
    repo = _repo(tmp_path)
    path = goal_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not utf-8")
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


def test_goal_cli_set_status_clear(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    assert main(["goal", "a CLI todo app", "--done", "true", "--max-iterations", "5"]) == 0
    capsys.readouterr()

    assert main(["goal", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["active"] is True
    assert data["vision"] == "a CLI todo app"
    assert data["max_iterations"] == 5

    assert main(["goal", "clear"]) == 0
    capsys.readouterr()
    assert main(["goal", "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["active"] is False


def test_goal_cli_next_emits_directive(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    main(["goal", "build x", "--done", "false"])
    capsys.readouterr()

    assert main(["goal", "next", "--json"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["status"] == "active"
    assert "build x" in decision["directive"]["prompt"]


def test_goal_cli_check_exit_code_reflects_done(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    main(["goal", "build x", "--done", "false"])
    capsys.readouterr()
    assert main(["goal", "check"]) == 1  # done-check fails

    main(["goal", "build x", "--done", "true"])
    capsys.readouterr()
    assert main(["goal", "check"]) == 0  # done-check passes -> goal complete


def test_goal_check_messages_misconfiguration_not_silent(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)

    # No goal set: exit 1 with a clear message, not a silent failure.
    assert main(["goal", "check"]) == 1
    assert "no active goal" in capsys.readouterr().out.lower()

    # Goal set without --done: exit 1, but explain there is no completion check
    # and how to add one (otherwise `/loop until: goal check` never terminates).
    main(["goal", "build x"])
    capsys.readouterr()
    assert main(["goal", "check"]) == 1
    out = capsys.readouterr().out
    assert "done-check" in out.lower()
    assert "--done" in out


def test_install_goal_instructions_is_idempotent(tmp_path):
    from looptight.integration import GOAL_START, install_goal_instructions

    assert install_goal_instructions(tmp_path)  # installs, returns changed paths
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert GOAL_START in claude
    assert "looptight goal next" in claude
    assert install_goal_instructions(tmp_path) == []  # already installed
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").count(GOAL_START) == 1


def test_goal_continuous_prints_driver_recipe(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    assert main(["goal", "build x", "--continuous"]) == 0
    out = capsys.readouterr().out
    assert "looptight goal check" in out  # the provider-neutral hands-off driver


def test_goal_check_exits_nonzero_without_a_goal_or_done_check(tmp_path, monkeypatch):
    # `/loop until: looptight goal check` relies on this contract: no goal, or a goal
    # with no --done command, both exit non-zero so the wrapper keeps looping.
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    assert main(["goal", "check"]) != 0  # no active goal

    main(["goal", "build x"])  # a goal without a --done check
    assert main(["goal", "check"]) != 0


def test_goal_human_output_paths(tmp_path, monkeypatch, capsys):
    # Cover the goal-mode human (non-JSON) output, the least battle-tested surface.
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)

    assert main(["goal"]) == 0  # bare goal, none active
    assert "no active goal" in capsys.readouterr().out.lower()

    main(["goal", "build a thing"])
    capsys.readouterr()
    assert main(["goal"]) == 0  # bare goal shows the active vision
    assert "build a thing" in capsys.readouterr().out

    assert main(["goal", "next"]) == 0  # human next prints the build directive
    assert "build a thing" in capsys.readouterr().out

    assert main(["goal", "clear"]) == 0
    assert "cleared" in capsys.readouterr().out.lower()


def test_run_done_check_returns_true_on_exit_0(tmp_path):
    _repo(tmp_path)
    assert run_done_check(tmp_path, "true") is True


def test_run_done_check_returns_false_on_nonzero_exit(tmp_path):
    _repo(tmp_path)
    assert run_done_check(tmp_path, "false") is False


def test_run_done_check_oserror_returns_false(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.goal.subprocess.run", lambda *a, **kw: (_ for _ in ()).throw(OSError("shell not found")))
    assert run_done_check(tmp_path, "true") is False


def test_goal_driver_recipe_includes_loop_hint_for_claude(tmp_path, monkeypatch):
    from looptight.protocol_commands import _goal_driver_recipe

    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda: "claude")
    recipe = _goal_driver_recipe(tmp_path)
    assert "/loop until: looptight goal check" in recipe


def test_goal_driver_recipe_omits_loop_hint_when_agent_unknown(tmp_path, monkeypatch):
    from looptight.protocol_commands import _goal_driver_recipe

    monkeypatch.setattr("looptight.protocol_commands.detect_agent", lambda: None)
    recipe = _goal_driver_recipe(tmp_path)
    assert "/loop until: looptight goal check" not in recipe


def test_goal_next_human_output_includes_iteration_number(tmp_path, monkeypatch, capsys):
    from looptight.cli import main

    monkeypatch.chdir(tmp_path)
    _repo(tmp_path)
    main(["goal", "build x"])
    capsys.readouterr()

    assert main(["goal", "next"]) == 0
    out = capsys.readouterr().out
    assert "iteration 1" in out.lower()


def test_clear_goal_returns_false_outside_git(tmp_path):
    # No git repo -> goal_path is None -> clear_goal returns False without raising.
    assert clear_goal(tmp_path) is False
