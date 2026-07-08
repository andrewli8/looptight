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
from looptight.integration_queue import CoordinationTimeout
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


def test_swarm_json_guard_emits_error_envelope(capsys):
    # A guard failure under --json must be a parseable error envelope, not plain text — matching
    # the swarm result envelope and every other --json command.
    import json as _json

    assert main(["swarm", "--json", "--agent", "codex"]) == 2  # missing --headless
    data = _json.loads(capsys.readouterr().out)
    assert data["command"] == "swarm" and data["status"] == "error"
    assert "--headless" in data["error"] and data["schema_version"] == 1

    assert main(["swarm", "--json", "--headless", "--agent", "codex", "--workers", "999"]) == 2
    data = _json.loads(capsys.readouterr().out)
    assert data["status"] == "error" and "workers must be between" in data["error"]


def test_swarm_cli_no_agent_guard(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.detect_agent", lambda: None)

    assert main(["swarm", "--headless", "--verify", "exit 0"]) == 2
    assert "No coding agent" in capsys.readouterr().out


def test_swarm_cli_no_verify_guard(tmp_path, monkeypatch, capsys):
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.detect_verify", lambda root: None)

    assert main(["swarm", "--headless", "--agent", "codex"]) == 2
    assert "No verify command" in capsys.readouterr().out


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


def test_run_swarm_guard_out_of_range_workers(tmp_path):
    """run_swarm line 688: workers < 1 or > MAX_WORKERS returns the guard error directly."""
    _repo(tmp_path)
    result = run_swarm(tmp_path, agent="fake", config=Config(verify="exit 0"), workers=0)
    assert result.error is not None and "workers must be between" in result.error
    assert result.workers == ()


def test_run_swarm_guard_no_verify(tmp_path):
    """run_swarm line 690: empty verify string returns the guard error directly."""
    _repo(tmp_path)
    result = run_swarm(tmp_path, agent="fake", config=Config(verify=""), workers=1)
    assert result.error == "no verify command configured"
    assert result.workers == ()


def test_run_swarm_guard_agent_unavailable(tmp_path, monkeypatch):
    """run_swarm line 694: an adapter whose is_available() is False returns the guard error."""
    _repo(tmp_path)

    class UnavailableAdapter(EditingAdapter):
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: UnavailableAdapter())
    result = run_swarm(tmp_path, agent="missingagent", config=Config(verify="exit 0"), workers=1)
    assert result.error is not None and "missingagent" in result.error and "not available" in result.error
    assert result.workers == ()


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


class FailingPlannerAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        (workdir / "docs").mkdir(exist_ok=True)
        (workdir / "docs" / "STATUS.md").write_text("## Next\n", encoding="utf-8")
        return IterationResult(transcript="", ok=False, error="planner provider crashed")


def test_swarm_fails_worker_when_status_inspection_fails(tmp_path, monkeypatch):
    # A worker whose `git status --porcelain` cannot be inspected is marked failed, not integrated.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        # Fail the worker's status (in its own worktree), not the invoking-worktree
        # cleanliness check at run_swarm's start (which also runs status --porcelain on root).
        if args[:2] == ("status", "--porcelain") and Path(root).resolve() != tmp_path.resolve():
            return subprocess.CompletedProcess(["git"], 1, "", "worker status broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.workers[0].status == "failed"
    assert "worker status broke" in (result.workers[0].error or "")


def test_swarm_fails_worker_when_commit_fails(tmp_path, monkeypatch):
    # A worker whose git commit of its in-scope changes fails is marked failed, not integrated.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        if args[:1] == ("commit",) and len(args) > 2 and str(args[2]).startswith("looptight:"):
            return subprocess.CompletedProcess(["git"], 1, "", "worker commit broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.workers[0].status == "failed"
    assert "worker commit broke" in (result.workers[0].error or "")


def test_swarm_fails_worker_when_change_detection_fails(tmp_path, monkeypatch):
    # If the worker's changed-file set cannot be determined, the worker is failed rather
    # than integrating an unknown change set.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    monkeypatch.setattr(
        "looptight.swarm._worker_changed_paths", lambda worker: (None, "cannot inspect changes")
    )

    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.workers[0].status == "failed"
    assert result.workers[0].error == "cannot inspect changes"


def test_prepare_workers_worktree_add_fail_surfaces_error(tmp_path, monkeypatch):
    # _prepare_workers line 345: if `git worktree add` fails, run_swarm returns the
    # error immediately — no workers are started.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    real_git = swarm._git

    def selective_git(root, *args):
        if args[:2] == ("worktree", "add"):
            return subprocess.CompletedProcess(["git"], 1, "", "no disk space")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.error is not None
    assert "no disk space" in result.error
    assert result.workers == ()


def test_prepare_workers_returns_error_when_no_git_commit(tmp_path, monkeypatch):
    # _prepare_workers line 331: git rev-parse HEAD fails in a repo with no commits,
    # so the guard returns the "requires a Git repository with at least one commit" error.
    # An empty repo has a clean git status (passes _git_clean) but no HEAD ref.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Looptight Test")
    _git(tmp_path, "config", "user.email", "test@looptight.dev")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1
    )
    assert result.error is not None
    assert "Git repository" in result.error
    assert "commit" in result.error
    assert result.workers == ()


def test_prepare_workers_branch_switch_fail_surfaces_error(tmp_path, monkeypatch):
    # _prepare_workers lines 357-359: if `git switch -c` fails after the worktree is
    # created, run_swarm removes the worktree and returns the error.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    real_git = swarm._git

    def selective_git(root, *args):
        if args[:2] == ("switch", "-q") and "-c" in args:
            return subprocess.CompletedProcess(["git"], 1, "", "ref conflict")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.error is not None
    assert "ref conflict" in result.error
    assert result.workers == ()


def test_worker_changed_paths_returns_none_on_git_failure(tmp_path, monkeypatch):
    # _worker_changed_paths lines 321-322: when git diff or ls-files fails,
    # return (None, error_message) instead of propagating — the swarm-level
    # wrapper that calls this function marks the worker failed with the error.
    from subprocess import CompletedProcess

    from looptight.swarm import _worker_changed_paths

    monkeypatch.setattr(
        "looptight.swarm._git",
        lambda workdir, *args, **kwargs: CompletedProcess(
            list(args), returncode=128, stdout="", stderr="not a git repository"
        ),
    )
    worker = Worker(
        number=1,
        task={"id": "t1", "goal": "fix it"},
        branch="lt/swarm/w1",
        worktree=tmp_path,
        base="abc123",
    )
    paths, error = _worker_changed_paths(worker)
    assert paths is None
    assert error == "not a git repository"


def test_worker_changed_paths_returns_fallback_message_when_stderr_empty(tmp_path, monkeypatch):
    # When git fails but stderr is empty, the fallback "could not inspect worker changes"
    # is returned so the caller always gets a non-empty error string.
    from subprocess import CompletedProcess

    from looptight.swarm import _worker_changed_paths

    monkeypatch.setattr(
        "looptight.swarm._git",
        lambda workdir, *args, **kwargs: CompletedProcess(
            list(args), returncode=1, stdout="", stderr=""
        ),
    )
    worker = Worker(
        number=1,
        task={"id": "t1", "goal": "fix it"},
        branch="lt/swarm/w1",
        worktree=tmp_path,
        base="abc123",
    )
    paths, error = _worker_changed_paths(worker)
    assert paths is None
    assert error == "could not inspect worker changes"


class RateLimitedAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        return IterationResult(
            transcript="", ok=False, error="provider rate limit reached; retry after 60s"
        )


def test_swarm_marks_a_rate_limited_worker_as_limited(tmp_path, monkeypatch):
    # A worker whose run loop ends on a provider rate limit is marked `limited`, not `failed`,
    # so the continuous swarm can wait it out instead of treating it as a failure.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: RateLimitedAdapter())

    result = run_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0", max_iterations=1), workers=1
    )

    assert result.workers[0].status == "limited"


class IdlePlannerAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        return IterationResult(transcript="nothing to plan")  # ok=True, no changes


def test_plan_next_tasks_returns_no_work_when_planner_makes_no_changes(tmp_path, monkeypatch):
    # A planner that succeeds but makes no changes signals no_work (the continuous swarm's
    # stop condition); the planner worktree is removed.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: IdlePlannerAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "no_work"


class OffScopePlannerAdapter(EditingAdapter):
    def run_iteration(self, goal, context, workdir, model=None):
        (workdir / "src" / "x.py").write_text("# planner went off-scope\n", encoding="utf-8")
        return IterationResult(transcript="planned")


def test_plan_next_tasks_rejects_changes_outside_status_md(tmp_path, monkeypatch):
    # The planner may only refresh docs/STATUS.md; a plan that edits any other file is rejected.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: OffScopePlannerAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "docs/STATUS.md" in (result.error or "")


def test_plan_next_tasks_fails_when_merge_to_root_conflicts(tmp_path, monkeypatch):
    # A failed merge of the accepted plan into the repo is aborted and reported as a planning
    # failure, never leaving a half-merged tree.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        if args[:2] == ("merge", "--no-commit"):
            return subprocess.CompletedProcess(["git"], 1, "", "merge conflict broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "merge conflict broke" in (result.error or "")


def test_plan_next_tasks_fails_when_planner_commit_fails(tmp_path, monkeypatch):
    # After a valid plan passes verify, a failing commit in the planner worktree is a clean
    # planning failure.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        if args[:1] == ("commit",):
            return subprocess.CompletedProcess(["git"], 1, "", "planner commit broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "planner commit broke" in (result.error or "")


def test_plan_next_tasks_fails_on_git_diff_inspection_failure(tmp_path, monkeypatch):
    # A git-diff failure while inspecting the planner worktree is a clean planning failure.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        if args[:1] == ("diff",):
            return subprocess.CompletedProcess(["git"], 1, "", "diff inspection broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "diff inspection broke" in (result.error or "")


def test_plan_next_tasks_fails_on_git_status_inspection_failure(tmp_path, monkeypatch):
    # A git failure while inspecting the planner worktree is a clean planning failure, not a crash.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(root, *args):
        if args[:2] == ("status", "--porcelain"):
            return subprocess.CompletedProcess(["git"], 1, "", "status inspection broke")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "status inspection broke" in (result.error or "")


def test_plan_next_tasks_accepts_and_merges_a_valid_plan(tmp_path, monkeypatch):
    # The planner success path: a valid grounded plan that passes verify is committed and
    # merged into the repo, returning status "planned".
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "planned"
    assert "Cover the source task" in (tmp_path / "docs" / "STATUS.md").read_text(encoding="utf-8")


def test_plan_next_tasks_fails_when_plan_verify_fails(tmp_path, monkeypatch):
    # A grounded plan that breaks the build is rejected: the planner runs verify in its
    # worktree and fails the plan when it does not pass.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 1")

    assert result.status == "failed"
    assert "planner verify" in (result.error or "")


def test_plan_next_tasks_fails_when_integration_verify_fails(tmp_path, monkeypatch):
    # plan_next_tasks runs run_verify twice: in the planner worktree (line 629) and on
    # root after merging (line 654). The existing "exit 1" test reaches only the worktree
    # call (line 629). This test passes the worktree verify but fails the root integration
    # verify, directly covering swarm.py:655's return PlanningResult("failed", ...).
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    from looptight.types import VerifyResult

    def selective_verify(verify_cmd, workdir):
        if workdir == tmp_path:
            return VerifyResult(passed=False, exit_code=1, output="integration verify broke")
        return VerifyResult(passed=True, exit_code=0)

    monkeypatch.setattr("looptight.swarm.run_verify", selective_verify)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "planner integration verify" in (result.error or "")


def test_plan_next_tasks_fails_when_integration_merge_commit_fails(tmp_path, monkeypatch):
    # plan_next_tasks commits the merge on root at line 662; line 664 is unreachable by
    # the existing commit-fails test (which fails the worktree commit at line 636, returning
    # before the root commit). This test lets the worktree commit and integration verify
    # succeed but fails only the root merge commit, covering swarm.py:664.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(workdir, *args):
        if workdir == tmp_path and args[:1] == ("commit",):
            return subprocess.CompletedProcess(["git"], 1, "", "integration merge commit broke")
        return real_git(workdir, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "integration merge commit broke" in (result.error or "")


def test_plan_next_tasks_fails_when_planner_provider_fails(tmp_path, monkeypatch):
    # A planner provider that returns ok=False is a clean planning failure carrying the
    # provider error, not an accepted plan.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: FailingPlannerAdapter())

    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "planner provider crashed" in (result.error or "")


def test_plan_next_tasks_fails_when_push_fails(tmp_path, monkeypatch):
    # plan_next_tasks lines 670-672: when push=True and git push exits non-zero after a
    # successful planner merge, the function returns a "failed" PlanningResult carrying
    # the push error. The selective_git wrapper lets every git call through except "push".
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git

    def selective_git(workdir, *args):
        if args[:1] == ("push",):
            return subprocess.CompletedProcess(["git", "push"], 1, "", "push rejected: non-fast-forward")
        return real_git(workdir, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0", push=True)

    assert result.status == "failed"
    assert "push rejected" in (result.error or "") or "could not push" in (result.error or "")


def test_plan_next_tasks_fails_when_rev_parse_head_fails(tmp_path, monkeypatch):
    # swarm.py:644: after a successful planner commit, rev-parse HEAD on the worktree
    # could fail (e.g. the worktree was removed mid-execution); plan_next_tasks must
    # return PlanningResult("failed", ...) carrying the diagnostic rather than crashing.
    _repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("# Status\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "docs")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: PlanningAdapter())

    real_git = swarm._git
    state = {"committed": False}

    def selective_git(root, *args):
        result = real_git(root, *args)
        if args[:1] == ("commit",) and result.returncode == 0:
            state["committed"] = True
            return result
        if args == ("rev-parse", "HEAD") and state["committed"]:
            return subprocess.CompletedProcess(["git"], 1, "", "fatal: not a git repository")
        return result

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "fatal: not a git repository" in (result.error or "") or "could not resolve planner commit" in (result.error or "")


def test_plan_next_tasks_fails_gracefully_outside_a_git_repo(tmp_path):
    # The continuous-swarm planner needs a Git repo with a commit; outside one it returns a
    # clear PlanningResult failure rather than crashing (the daemon must keep its footing).
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")
    assert result.status == "failed"
    assert "Git repository" in (result.error or "")


def test_plan_next_tasks_fails_when_planner_worktree_creation_fails(tmp_path, monkeypatch):
    # _create_planner_worktree's git worktree add failure return (swarm.py:570) is distinct
    # from the git-prereq failure: rev-parse succeeds, but worktree add exits nonzero
    # (e.g. storage full).  plan_next_tasks must return PlanningResult("failed", ...) carrying
    # the stderr message rather than crashing.
    _repo(tmp_path)
    real_git = swarm._git

    def selective_git(root, *args):
        if args[:2] == ("worktree", "add"):
            return subprocess.CompletedProcess(["git"], 1, "", "no space left on device")
        return real_git(root, *args)

    monkeypatch.setattr("looptight.swarm._git", selective_git)
    result = plan_next_tasks(tmp_path, agent="fake", verify="exit 0")

    assert result.status == "failed"
    assert "no space left on device" in (result.error or "")


def test_swarm_cli_continuous_prints_round_summary(tmp_path, monkeypatch, capsys):
    # Continuous mode prints a "continuous · N rounds · M plans · K resumes" summary.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "looptight.swarm.run_continuous_swarm",
        lambda *a, **k: SwarmResult((), rounds=3, plans=1, resumes=0),
    )
    main([
        "swarm", "--headless", "--agent", "codex", "--verify", "exit 0",
        "--continuous", "--max-rounds", "5",
    ])
    out = capsys.readouterr().out
    assert "continuous" in out and "3 rounds" in out and "1 plan" in out and "1 plans" not in out


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


def test_run_swarm_returns_push_failed_when_publish_queue_fails(tmp_path, monkeypatch):
    # swarm.py:742 — when push=True, at least one worker merged, and _publish_via_queue
    # returns anything other than "pushed", run_swarm returns SwarmResult with pushed="failed".
    # A regression removing this check would silently claim success even when commits failed
    # to publish via the integration queue.
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    monkeypatch.setattr("looptight.swarm._publish_via_queue", lambda *_a, **_kw: "failed")

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
        push=True,
    )

    assert result.pushed == "failed"
    assert any(w.status == "merged" for w in result.workers)


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
    assert lines[-1] == "2 workers · 2 merged"


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
    # All workers merged → no retained worktrees, so the next line must NOT mention inspecting them.
    assert "next: continue with `looptight next --json`" in out
    assert "retained worktrees" not in out
    assert out.splitlines()[-1] == "1 worker · 1 merged"


def test_swarm_next_line_points_at_worktrees_on_failure(tmp_path, monkeypatch, capsys):
    # A failed worker retains a worktree, so the next line should point the operator at it.
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: UnrelatedEditingAdapter())

    assert main(
        ["swarm", "--headless", "--agent", "codex", "--verify", "exit 0", "--workers", "1"]
    ) == 1

    out = capsys.readouterr().out
    assert "worktree retained for recovery" in out  # a failed worker retained one
    assert "next: inspect the retained worktrees above" in out


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

    assert swarm._swarm_tally(workers) == "4 workers · 2 merged · 1 failed · 1 timeout"


def test_swarm_tally_has_no_dangling_separator_when_empty():
    # A planner-failure round retains a worktree but produces zero workers. The tally must read
    # "0 workers" cleanly, not "0 workers · " with a dangling separator and empty breakdown.
    assert swarm._swarm_tally([]) == "0 workers"


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


def test_swarm_marks_worker_failed_when_lease_is_lost(tmp_path, monkeypatch):
    # When coordinator.lease_for returns None for a verified worker (lease reaped before
    # integration), _integrate_via_queue marks the worker failed with "lost task lease"
    # — the recovery invariant has no other test.
    _repo(tmp_path)

    class _LostLeaseCoordinator:
        def lease_for(self, fingerprint, run_id):
            return None

        def next_queued_integration(self):
            return None

        def close(self):
            pass

    class _FakeCoordinatorClass:
        @staticmethod
        def open(root, **kw):
            return _LostLeaseCoordinator()

    monkeypatch.setattr("looptight.swarm.Coordinator", _FakeCoordinatorClass)

    worker = Worker(
        number=0,
        task={"id": "abc123", "goal": "test goal", "source": "test"},
        branch="worker-0",
        worktree=tmp_path,
        base="HEAD",
        status="verified",
        run_id="run-xyz",
    )

    from looptight.swarm import _integrate_via_queue
    _integrate_via_queue(tmp_path, [worker], "exit 0")

    assert worker.status == "failed"
    assert "lost task lease" in (worker.error or "")


def test_swarm_marks_worker_failed_when_integration_did_not_run(tmp_path, monkeypatch):
    # When lease_for returns a valid Lease and enqueue_integration stores an id but the
    # Integrator's next_queued_integration returns None (empty queue despite the enqueue),
    # _integrate_via_queue marks the queued worker failed with "integration did not run".
    from looptight.coordinator import Lease

    _repo(tmp_path)

    class _DropIntegrationCoordinator:
        def lease_for(self, fingerprint, run_id):
            return Lease(fingerprint, run_id, 0, {}, 0)

        def enqueue_integration(self, lease, target_ref, candidate_sha):
            return "dropped-integration-id"

        def next_queued_integration(self):
            return None  # pretend the queue is empty

        def close(self):
            pass

    class _FakeCoordinatorClass:
        @staticmethod
        def open(root, **kw):
            return _DropIntegrationCoordinator()

    monkeypatch.setattr("looptight.swarm.Coordinator", _FakeCoordinatorClass)

    worker = Worker(
        number=0,
        task={"id": "abc123", "goal": "test goal", "source": "test"},
        branch="worker-0",
        worktree=tmp_path,
        base="HEAD",
        status="verified",
        run_id="run-xyz",
    )

    from looptight.swarm import _integrate_via_queue
    _integrate_via_queue(tmp_path, [worker], "exit 0")

    assert worker.status == "failed"
    assert "integration did not run" in (worker.error or "")


def test_swarm_handles_coordination_timeout(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    def _raise(*_a, **_kw):
        raise CoordinationTimeout("lock busy")

    monkeypatch.setattr("looptight.swarm._integrate_via_queue", _raise)

    result = run_swarm(
        tmp_path,
        agent="fake",
        config=Config(verify="exit 0", max_iterations=1),
        workers=1,
    )

    assert result.error is not None
    assert "lock busy" in result.error


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


def test_planned_tasks_grounded_rejects_zero_line_number(tmp_path):
    # swarm.py:158 — the `int(line_text) < 1` half of the line-bounds check was never
    # tested; a mutation changing `< 1` to `< 0` would accept :0 citations silently.
    from looptight.discovery import Candidate
    from looptight.swarm import _planned_tasks_are_grounded

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n" * 5, encoding="utf-8")

    c = Candidate(
        title="t", source="status-next", location="docs/STATUS.md:5",
        suggested_verify=None, score=0.0,
        detail="Fix it. Evidence: `src/a.py:0`", acceptance="ok",
    )
    assert _planned_tasks_are_grounded(tmp_path, [c]) is False


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


def test_task_paths_falls_back_to_parent_dir_counterpart(tmp_path):
    # When evidence points at a nested source file (src/adapters/claude.py), the
    # stem-only counterpart test_claude.py is absent, but test_adapters.py (named
    # for the parent directory) is present — _task_paths must include it so a
    # worker editing tests/test_adapters.py is not falsely rejected as out-of-scope.
    from looptight.swarm import _task_paths

    (tmp_path / "src" / "adapters").mkdir(parents=True)
    (tmp_path / "src" / "adapters" / "claude.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_adapters.py").write_text("x", encoding="utf-8")
    # no tests/test_claude.py

    paths = _task_paths(
        tmp_path,
        {"location": "docs/STATUS.md:1", "evidence": "Evidence: `src/adapters/claude.py:1`"},
    )
    assert "tests/test_adapters.py" in paths


def test_task_paths_includes_colocated_js_ts_test_counterpart(tmp_path):
    # A JS/TS worker whose evidence is a source file must be allowed to edit its colocated test
    # (foo.test.ts / foo.spec.ts beside the source), not just Python's tests/test_*.py layout —
    # else it is falsely rejected as "changed files outside task scope".
    from looptight.swarm import _task_paths

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.ts").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "foo.test.ts").write_text("x", encoding="utf-8")
    # no foo.spec.ts on disk — only the present counterpart is allowed

    paths = _task_paths(tmp_path, {"location": "docs/STATUS.md:1", "evidence": "Evidence: `src/foo.ts:1`"})
    assert "src/foo.ts" in paths and "src/foo.test.ts" in paths
    assert "src/foo.spec.ts" not in paths  # absent counterparts are not invented


def test_task_paths_reverse_maps_test_to_its_unambiguous_source(tmp_path):
    # A skipped-test task's evidence IS the test, but its acceptance ("un-skip and pass project
    # verification") can need editing the module under test. Allow the unambiguous source module.
    from looptight.swarm import _task_paths

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "parser.py").write_text("x", encoding="utf-8")  # the one module under test
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_parser.py").write_text("x", encoding="utf-8")

    paths = _task_paths(tmp_path, {"location": "S:1", "evidence": "Evidence: `tests/test_parser.py:3`"})
    assert "tests/test_parser.py" in paths and "src/parser.py" in paths


def test_task_paths_reverse_is_conservative_when_source_is_ambiguous(tmp_path):
    # Two modules named utils.py: the test->source mapping is ambiguous, so neither is added (we do
    # not open every same-named file in the repo to a worker's scope). The test file stays in scope.
    from looptight.swarm import _task_paths

    for pkg in ("a", "b"):
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "utils.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_utils.py").write_text("x", encoding="utf-8")

    paths = _task_paths(tmp_path, {"location": None, "evidence": "Evidence: `tests/test_utils.py:1`"})
    assert "tests/test_utils.py" in paths  # the evidence test stays in scope
    assert "a/utils.py" not in paths and "b/utils.py" not in paths  # ambiguous source not added


def test_task_paths_reverse_maps_js_test_to_colocated_source(tmp_path):
    from looptight.swarm import _task_paths

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.ts").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "api.test.ts").write_text("x", encoding="utf-8")

    paths = _task_paths(tmp_path, {"location": "S:1", "evidence": "Evidence: `src/api.test.ts:2`"})
    assert "src/api.test.ts" in paths and "src/api.ts" in paths


def test_task_paths_reverse_maps_js_tests_dir_to_parent_source(tmp_path):
    # A test inside __tests__/ has its source in the parent dir (src/__tests__/api.test.ts -> src/api.ts).
    from looptight.swarm import _task_paths

    (tmp_path / "src" / "__tests__").mkdir(parents=True)
    (tmp_path / "src" / "api.ts").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "__tests__" / "api.test.ts").write_text("x", encoding="utf-8")

    paths = _task_paths(tmp_path, {"location": "S:1", "evidence": "Evidence: `src/__tests__/api.test.ts:2`"})
    assert "src/api.ts" in paths


def test_task_paths_test_counterpart_works_for_flat_python_layout(tmp_path):
    # Not every project uses a src/ layout. A flat package (mypackage/foo.py) or a top-level module
    # (app.py) keeps its test at tests/test_{stem}.py, so a worker must be allowed to edit it.
    from looptight.swarm import _task_paths

    (tmp_path / "mypackage").mkdir()
    (tmp_path / "mypackage" / "foo.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_foo.py").write_text("x", encoding="utf-8")
    (tmp_path / "app.py").write_text("x", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("x", encoding="utf-8")

    flat = _task_paths(tmp_path, {"location": "S:1", "evidence": "Evidence: `mypackage/foo.py:1`"})
    assert "tests/test_foo.py" in flat  # flat package, no src/
    top = _task_paths(tmp_path, {"location": "S:1", "evidence": "Evidence: `app.py:1`"})
    assert "tests/test_app.py" in top  # top-level module


def test_task_paths_includes_js_ts_tests_dir_counterpart(tmp_path):
    # JS/TS projects also keep tests in a sibling __tests__/ directory; a worker on src/bar.ts must
    # be allowed to edit src/__tests__/bar.test.ts without a false out-of-scope rejection.
    from looptight.swarm import _task_paths

    (tmp_path / "src" / "__tests__").mkdir(parents=True)
    (tmp_path / "src" / "bar.ts").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "__tests__" / "bar.spec.ts").write_text("x", encoding="utf-8")

    paths = _task_paths(tmp_path, {"location": "docs/STATUS.md:1", "evidence": "Evidence: `src/bar.ts:1`"})
    assert "src/bar.ts" in paths and "src/__tests__/bar.spec.ts" in paths


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


def test_continuous_swarm_planner_limit_persists_to_terminal(tmp_path, monkeypatch):
    # When the planning round hits a provider limit and the resume cap is reached, the
    # continuous swarm returns reason limit.
    from looptight.swarm import REASON_LIMIT

    _repo(tmp_path)
    (tmp_path / "src" / "a.py").write_text("# done\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# done\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "done")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    monkeypatch.setattr(
        "looptight.swarm.plan_next_tasks",
        lambda *a, **k: PlanningResult("failed", "provider rate limit reached; retry after 5s", None),
    )

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"),
        workers=1, max_rounds=0, generate_ideas=True,
        resume_on_limit=True, limit_max_resumes=1, sleep=lambda s: None,
    )

    assert result.reason == REASON_LIMIT
    # Proper singular agreement at the cap of 1 — "after 1 resume", not "1 resumes".
    assert "after 1 resume" in (result.error or "") and "1 resumes" not in (result.error or "")


def test_continuous_swarm_returns_on_planner_failure(tmp_path, monkeypatch):
    # Work exhausted, then the planning round itself fails: the continuous swarm ends with reason
    # error carrying the planner error.
    from looptight.swarm import REASON_ERROR

    _repo(tmp_path)
    (tmp_path / "src" / "a.py").write_text("# done\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# done\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "done")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())
    monkeypatch.setattr(
        "looptight.swarm.plan_next_tasks",
        lambda *a, **k: PlanningResult("failed", "planner crashed", tmp_path / "wt"),
    )

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"),
        workers=1, max_rounds=0, generate_ideas=True,
    )

    assert result.reason == REASON_ERROR
    assert "planner crashed" in (result.error or "")


def test_continuous_swarm_returns_on_top_level_error(tmp_path, monkeypatch):
    # A round whose run_swarm returns a top-level error (e.g. an integration timeout) ends the
    # continuous swarm immediately with reason error.
    from looptight.swarm import REASON_ERROR

    _repo(tmp_path)
    monkeypatch.setattr(
        "looptight.swarm.run_swarm", lambda *a, **k: SwarmResult((), "integration coordination timeout")
    )

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1, max_rounds=0
    )

    assert result.reason == REASON_ERROR
    assert result.error == "integration coordination timeout"


def test_continuous_swarm_returns_at_max_rounds_with_no_work(tmp_path, monkeypatch):
    # All tasks already done: with max_rounds=1 the continuous swarm returns after the single
    # empty round rather than planning.
    _repo(tmp_path)
    (tmp_path / "src" / "a.py").write_text("# done\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("# done\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "done")
    monkeypatch.setattr("looptight.swarm.get_adapter", lambda name: EditingAdapter())

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1, max_rounds=1
    )

    assert result.rounds == 1


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
    # The commit is recorded durably (state `committed` + result_sha) before the ref advance,
    # so recovery does not depend on the volatile worktree.
    assert db.integration(integration_id).state == "committed"
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


def test_task_paths_safety_guards(tmp_path):
    # line 265: None reference is skipped (location=None, no evidence → empty set)
    from looptight.swarm import _task_paths

    paths = _task_paths(tmp_path, {"location": None, "evidence": ""})
    assert paths == set()

    # line 269: bare path with no `:line` suffix is still added to scope (non-empty)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("x", encoding="utf-8")
    paths = _task_paths(tmp_path, {"location": None, "evidence": "Evidence: src/foo.py"})
    assert "src/foo.py" in paths

    # line 272: absolute path is rejected (continue)
    paths = _task_paths(tmp_path, {"location": None, "evidence": "Evidence: /etc/passwd:1"})
    assert paths == set()

    # line 272: `..`-containing path is rejected (continue)
    paths = _task_paths(tmp_path, {"location": None, "evidence": "Evidence: ../evil.py:1"})
    assert paths == set()


def test_continuous_swarm_exits_naturally_after_max_rounds_with_workers(tmp_path, monkeypatch):
    # swarm.py:884 — the `return SwarmResult(...)` after the while loop — is reached when
    # max_rounds > 0 and workers succeed in the final round (so `continue` brings the loop
    # back to the while condition, which is now False). The existing max-rounds test uses an
    # empty round (no workers), which hits the early return at line 833 instead.
    merged_worker = Worker(
        1,
        {"id": "task-1", "source": "status-next", "goal": "cover line 884", "location": None},
        "branch",
        tmp_path / "worker",
        "base",
        status="merged",
    )
    monkeypatch.setattr(
        "looptight.swarm.run_swarm",
        lambda *args, **kwargs: SwarmResult((merged_worker,)),
    )

    result = run_continuous_swarm(
        tmp_path, agent="fake", config=Config(verify="exit 0"), workers=1, max_rounds=1
    )

    assert result.rounds == 1
    assert result.error is None
    assert merged_worker in result.workers


def test_publish_state_swallows_write_oserror(tmp_path, monkeypatch):
    # _publish_state's except OSError: pass (swarm.py:191) must absorb a write failure
    # so an I/O error never disrupts orchestration — observability is best-effort.
    from looptight.swarm import _publish_state

    monkeypatch.setattr("looptight.swarm.write_state", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    _publish_state(tmp_path, [], "ok")  # must not raise


def test_remove_worker_worktree_swallows_rmdir_oserror_on_non_empty_parent(tmp_path, monkeypatch):
    # When a sibling worktree occupies the parent directory, rmdir() fails with
    # ENOTEMPTY; the guard must swallow it so cleanup succeeds and returns 0.
    root = tmp_path / "repo"
    root.mkdir()
    _repo(root)
    worktree = tmp_path / "wt" / "w1"
    worktree.parent.mkdir()
    _git(root, "worktree", "add", "-q", "--detach", str(worktree))

    monkeypatch.setattr(Path, "rmdir", lambda self: (_ for _ in ()).throw(OSError("not empty")))
    result = swarm._remove_worker_worktree(root, worktree)
    assert result.returncode == 0


def test_swarm_git_oserror_returns_127(tmp_path, monkeypatch):
    # swarm._git()'s except OSError branch (swarm.py:217) converts a launch
    # failure into a CompletedProcess with returncode 127 and the error in stderr,
    # so callers that check returncode always get a valid object instead of an exception.
    monkeypatch.setattr(
        "looptight.swarm.subprocess.run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("git not found")),
    )
    result = swarm._git(tmp_path, "status")
    assert result.returncode == 127
    assert "git not found" in result.stderr


def test_publish_via_queue_returns_failed_when_publication_stays_incomplete(tmp_path, monkeypatch):
    # _publish_via_queue line 483: when Publisher.reconcile() runs but at least one
    # enqueued publication never reaches "complete" state, the function returns "failed".
    from dataclasses import dataclass
    from looptight.swarm import _publish_via_queue

    _repo(tmp_path)

    @dataclass
    class _FakePublication:
        state: str

    class _FakeCoordinator:
        def enqueue_publication(self, integration_id, remote, remote_ref):
            return "pub-id-1"

        def publication(self, pub_id):
            return _FakePublication(state="queued")  # never "complete"

        def close(self):
            pass

    class _FakeCoordinatorClass:
        @staticmethod
        def open(root, **kw):
            return _FakeCoordinator()

    class _NoOpPublisher:
        def __init__(self, coordinator, lock_timeout_s=None):
            pass

        def reconcile(self, root):
            pass  # publications stay incomplete

    monkeypatch.setattr("looptight.swarm.Coordinator", _FakeCoordinatorClass)
    monkeypatch.setattr("looptight.swarm.Publisher", _NoOpPublisher)

    worker = Worker(
        number=1,
        task={"id": "t1", "goal": "fix it"},
        branch="lt/swarm/w1",
        worktree=tmp_path,
        base="HEAD",
        status="merged",
        run_id="run-1",
    )
    worker.integration_id = "integ-id-1"

    result = _publish_via_queue(tmp_path, [worker])
    assert result == "failed"
