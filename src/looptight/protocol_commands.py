"""Machine-facing validation and task protocol command handlers."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .claims import MARKER_NAME, ClaimStore, claim_dir, has_live_claim, owner_id
from .config import ConfigError, load_config
from .console import Console
from .coordinator import Coordinator, MigrationBlocked, coordination_scope, current_run_id
from .detect import detect_agent, detect_verify
from .ui import read_state, render_state_panel
from .verify import run_verify


def cmd_verify(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    try:
        config = load_config()
        command = args.verify or config.verify or detect_verify(workdir)
    except ConfigError as exc:
        if args.json:
            _print_verify_json(status="error", output=f"config error: {exc}")
        else:
            console.print(f"[red]config error:[/red] {exc}")
        return 2
    if not command:
        message = "No verify command found. Pass --verify or run `looptight init`."
        if args.json:
            _print_verify_json(status="error", output=message)
        else:
            console.print(f"[red]{message}[/red]")
        return 2
    policy_error = _verify_policy_error(command, config, workdir)
    if policy_error:
        if args.json:
            _print_verify_json(status="error", output=policy_error)
        else:
            console.print(f"[red]policy error:[/red] {policy_error}")
        return 2
    result = run_verify(command, workdir)
    stall = _stall_signal(workdir, command, result, getattr(args, "patience", 0) or 0)
    if args.json:
        _print_verify_json(
            status=result.status,
            exit_code=result.exit_code,
            score=result.score,
            duration_ms=round(result.duration_s * 1000, 3),
            output=result.output,
            error=result.error,
            stall=stall,
        )
        return _verify_exit_code(result.status)
    style = "green" if result.passed else "red"
    console.print(f"verify: [{style}]{result.short()}[/{style}] (exit {result.exit_code})")
    console.print(f"verifier result: {result.status}")
    console.print(f"changed files: {_changed_files(workdir)}")
    if stall and stall.get("escalation"):
        console.print(f"[yellow]stalled:[/yellow] {stall['escalation']['summary']}")
    if result.passed:
        next_step = "next: review the diff, update status, then commit"
    elif stall and stall.get("escalation"):
        # The stall says the current approach is not progressing; do not advise
        # "continue fixing" — point at a different approach or human review.
        next_step = "next: no progress across these attempts — try a different approach or get a human review"
    else:
        next_step = "next: continue fixing, then rerun `looptight verify --json`"
    console.print(next_step)
    return _verify_exit_code(result.status)


def _stall_signal(workdir: Path, command: str, result, patience: int) -> dict | None:
    """Session-native value-aware stopping: persist the verify trajectory and,
    when ``--patience`` is set, return the stall verdict (and escalation evidence
    when stalled). ``None`` when the feature is off, so the default contract holds.
    """
    if patience <= 0:
        return None
    from . import trajectory
    from .metacog import (
        Decision,
        _failure_lines,
        assess,
        escalation_from_signals,
        progress_signal,
    )
    from .types import StopReason

    entries = trajectory.record(
        workdir, command, progress_signal(result), _failure_lines(result.output),
        passed=result.passed,
    )
    if result.passed or not entries:
        return None
    history = [entry["signal"] for entry in entries]
    decision = assess(history, patience)
    stall: dict = {"decision": decision.value}
    if decision in (Decision.STOP_NO_PROGRESS, Decision.ESCALATE):
        stop_reason = (
            StopReason.ESCALATED if decision is Decision.ESCALATE else StopReason.NO_PROGRESS
        )
        failure_sets = [set(entry["failures"]) for entry in entries]
        # The escalation evidence is additive: present only when actually stalled,
        # matching the SPEC ("when stalled") and the omit-when-absent shape of the
        # outer stall key itself.
        stall["escalation"] = escalation_from_signals(history, failure_sets, stop_reason).as_dict()
    return stall


def _verify_exit_code(status: str) -> int:
    """Separate a valid negative verdict from an invalid verifier execution."""
    return {"pass": 0, "fail": 1, "timeout": 2, "error": 2}[status]


def _print_verify_json(
    *,
    status: str,
    output: str,
    exit_code: int | None = None,
    score: float | None = None,
    duration_ms: float = 0.0,
    error: str | None = None,
    stall: dict | None = None,
) -> None:
    """Emit the v1 verifier contract without terminal styling or wrapping.

    The ``stall`` object is additive and present only under ``--patience`` (the
    session-native value-aware stopping signal), so the default contract is
    unchanged."""
    payload = {
        "schema_version": 1,
        "command": "verify",
        "status": status,
        "exit_code": exit_code,
        "score": score,
        "duration_ms": duration_ms,
        "output": output,
        "error": error,
    }
    if stall is not None:
        payload["stall"] = stall
    print(json.dumps(payload, sort_keys=True))


def _eval_line(score: object) -> str:
    """One-line human summary of an idea-batch eval (a BatchScore)."""
    return (
        "idea-batch eval (docs/STATUS.md ## Next): "
        f"grounded {score.grounded}/{score.size} "
        f"(groundedness {score.groundedness:.2f}) · "
        f"areas {score.flexibility} · distinct {score.distinct} · "
        f"bounded {'yes' if score.bounded else 'no'}"
    )


def cmd_propose(args: argparse.Namespace, console: Console) -> int:
    from .propose import propose

    source = getattr(args, "source", None)
    if source:
        # Filter before limiting, so `--source X --limit N` shows up to N of source X
        # rather than only those that survive the overall top-N ranking cut.
        candidates = [c for c in propose(Path.cwd(), limit=0) if c.source == source]
        if args.limit and args.limit > 0:
            candidates = candidates[: args.limit]
    else:
        candidates = propose(Path.cwd(), limit=args.limit)
    evaluation = None
    if getattr(args, "eval_batch", False):
        from .idea_eval import score_status_next

        evaluation = score_status_next(Path.cwd())

    if args.json:
        payload: dict[str, object] | list[dict[str, object]] = [c.__dict__ for c in candidates]
        if evaluation is not None:
            payload = {"candidates": [c.__dict__ for c in candidates], "eval": evaluation.as_dict()}
        print(json.dumps(payload, indent=2))
        return 0

    if not candidates and source:
        # A filtered query found nothing for *this* source — say so, rather than
        # claiming a clean tree when other sources may still have work.
        console.print(f"No candidate tasks from source [cyan]{source}[/cyan].")
        console.print("Drop [bold]--source[/bold] to see every source.")
    elif not candidates:
        console.print("No candidate tasks found from repo signals.")
        console.print(
            "Run [bold]looptight next[/bold] to generate grounded tasks, or "
            "[bold]looptight goal \"<vision>\"[/bold] to build toward a goal."
        )
    else:
        noun = "task" if len(candidates) == 1 else "tasks"
        console.print(
            f"[bold]{len(candidates)} candidate {noun}[/bold] "
            "(grouped by source priority; pick what to run):"
        )
        console.print()
        last_source: str | None = None
        for i, candidate in enumerate(candidates, 1):
            if candidate.source != last_source:
                console.print(
                    f"[cyan]{candidate.source}[/cyan] [dim](source priority "
                    f"{int(candidate.score)})[/dim]"
                )
                last_source = candidate.source
            where = f" [dim]{candidate.location}[/dim]" if candidate.location else ""
            console.print(f"  {i}. {candidate.title}{where}")
        console.print()
        console.print(
            "[dim]Ranking is a source-priority heuristic. The operating agent selects the "
            "highest-value actionable task in the current session, validates it with[/dim] "
            "[bold]looptight verify[/bold][dim], then commits and pushes a coherent change.[/dim]"
        )

    if evaluation is not None:
        console.print(_eval_line(evaluation))
    return 0


def cmd_next(args: argparse.Namespace, console: Console) -> int:
    """Print the single next task for the current session to execute."""
    from .checkpoint import is_git_repo
    from .tasks import NextResult, next_task

    workdir = Path.cwd()
    # Refuse outside a Git repository like `doctor`, `status`, and `verify` do. Without
    # this guard `next` would treat a non-repo as an empty clean queue and hand back a
    # `generate_ideas` directive, driving a host session to build into a directory with no
    # checkpoints or claim coordinator (tasks.py's git probes silently no-op outside Git).
    if not is_git_repo(workdir):
        result = NextResult(status="error", error="not_git")
        if args.json:
            print(json.dumps(result.as_dict(), sort_keys=True))
        else:
            console.print(
                "[red]not a git repo:[/red] run `looptight next` inside a Git repository; "
                "it needs Git for checkpoints and task claims."
            )
        return 2

    idea_generation = load_config().idea_generation and not args.no_ideas
    result = next_task(workdir, idea_generation=idea_generation)
    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
        return 2 if result.status == "error" else 0
    # Human output is goal-aware like `status`: `next` runs evidence discovery, so
    # if a build goal is active the user likely wants `goal next` instead.
    from .goal import read_goal

    if read_goal(Path.cwd()) is not None:
        console.print(
            "note: a build goal is active — `looptight goal next` drives it; "
            "`next` runs evidence-based discovery instead."
        )
    if result.status == "error":
        if result.error == "dirty_worktree":
            console.print(
                "[red]dirty worktree:[/red] commit or stash your changes before "
                "claiming a task. If it is only build artifacts (e.g. __pycache__ "
                "left by your test command), add them to .gitignore."
            )
        else:
            console.print(f"[red]error:[/red] {result.error}")
    elif result.status == "no_work":
        if result.directive is not None:
            print(
                "NO_WORK · queue empty — generate grounded tasks for docs/STATUS.md "
                "Next (each with Evidence and Acceptance) and continue, or pass "
                "--no-ideas to stop."
            )
        else:
            print("NO_WORK")
    else:
        assert result.task is not None
        print(f"selected task: {result.task['goal']}")
        where = f" from {result.task['location']}" if result.task.get("location") else ""
        print(f"why: {result.task['source']}{where}")
        evidence = result.task.get("evidence")
        if evidence:
            print(f"evidence: {evidence}")
        acceptance = result.task.get("acceptance")
        if acceptance:
            print(f"acceptance: {acceptance}")
        print("next: implement the task, run `looptight verify`, and commit only if it passes")
    return 2 if result.status == "error" else 0


def _changed_files(workdir: Path) -> str:
    files = _changed_file_list(workdir)
    if files is None:
        return "unavailable"
    return ", ".join(files) if files else "none"


def _changed_entries(workdir: Path) -> list[list[str]] | None:
    """One entry per `git status --short` line. A rename/copy entry carries both
    sides (`old -> new`); every other entry is a single path. The *count* of changed
    files is the number of entries (a rename is one file), while protected-path
    checks must scan every side — so the two concerns read this, not a flat list."""
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    entries: list[list[str]] = []
    for line in result.stdout.splitlines():
        if len(line) <= 3:
            continue
        rest = line[3:]
        # A rename/copy entry is `old -> new`; both paths must be checked so a
        # rename of a protected file cannot slip past the policy. Git C-quotes paths
        # with special characters in `--short` output, so strip surrounding quotes.
        sides = rest.split(" -> ", 1) if " -> " in rest else [rest]
        entries.append([_unquote_git_path(side) for side in sides])
    return entries


def _changed_file_list(workdir: Path) -> list[str] | None:
    """Flat list of every changed path (both sides of a rename) — for the
    protected-path scan and human display. A rename contributes two paths here."""
    entries = _changed_entries(workdir)
    if entries is None:
        return None
    return [side for entry in entries for side in entry]


def _unquote_git_path(path: str) -> str:
    """Strip git's surrounding double-quotes from a path it quoted for special chars."""
    if len(path) >= 2 and path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    return path


def _verify_policy_error(command: str, config, workdir: Path) -> str | None:
    if config.allowed_verify_commands and command not in config.allowed_verify_commands:
        return f"verify command not allowed by policy: {command}"
    entries = _changed_entries(workdir) or []
    # Count changed files, not paths: a rename is one file (one entry), so renaming
    # a single file is not double-counted against max_changed_files.
    changed_count = len(entries)
    if config.max_changed_files is not None and changed_count > config.max_changed_files:
        return (
            f"changed file count exceeds policy max_changed_files="
            f"{config.max_changed_files}: {changed_count}"
        )
    files = [side for entry in entries for side in entry]
    for changed in files:
        for protected in config.protected_paths:
            prefix = protected.rstrip("/")
            # Exact path, directory prefix (`config/` protects all of config/), or a
            # glob (`config/*`, `*.env`). Globs must be honored, or a `*` pattern
            # silently fails open and leaves the named files unprotected.
            if (
                changed == prefix
                or changed.startswith(prefix + "/")
                or fnmatch.fnmatch(changed, protected)
            ):
                return f"protected path changed by policy: {changed}"
    return None


def cmd_migrate(args: argparse.Namespace, console: Console) -> int:
    """Activate the repository coordinator, migrating from legacy file claims."""
    workdir = Path.cwd()
    coordinator = Coordinator.open(workdir)
    if coordinator is None:
        console.print("[red]migrate requires a Git repository.[/red]")
        return 2
    already_active = (coordinator.path.parent / MARKER_NAME).is_file()
    try:
        coordinator.activate_from_legacy()
    except MigrationBlocked as exc:
        console.print(f"[red]cannot activate the coordinator:[/red] {exc}")
        return 2
    finally:
        coordinator.close()
    if args.json:
        print(json.dumps({"schema_version": 1, "command": "migrate", "status": "active"}, sort_keys=True))
    else:
        # Distinguish a no-op re-run from a fresh activation, like install-hook.
        console.print("coordinator already active" if already_active else "coordinator active")
    return 0


def _watch_status(
    workdir: Path,
    console: Console,
    *,
    interval: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    max_ticks: int = 0,
    clear: bool = True,
) -> int:
    """Re-render the swarm/daemon panel on an interval until interrupted.

    Reads the latest state each tick. ``sleep`` and ``max_ticks`` are injected so a
    test can drive a single render without waiting. Returns the number of ticks.
    """
    ticks = 0
    try:
        while max_ticks == 0 or ticks < max_ticks:
            panel = render_state_panel(read_state(workdir)) or "swarm: no active workers"
            if clear:
                console.print("\033[2J\033[H", end="")  # clear screen, cursor home
            console.print(panel)
            ticks += 1
            if max_ticks and ticks >= max_ticks:
                break
            sleep(interval)
    except KeyboardInterrupt:
        pass
    return ticks


def cmd_status(args: argparse.Namespace, console: Console) -> int:
    """Report safety state without running validation or claiming work."""
    workdir = Path.cwd()
    if getattr(args, "watch", False):
        _watch_status(workdir, console, interval=getattr(args, "interval", 2.0))
        return 0
    config = load_config()
    verify = config.verify or detect_verify(workdir)
    agent = config.agent or detect_agent()
    try:
        git = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workdir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        git = None
    workspace = (
        "not_git"
        if git is None or git.returncode != 0
        else ("dirty" if git.stdout.strip() else "clean")
    )

    coordinator = Coordinator.open(workdir)
    claimed_task = None
    active_claims = 0
    coordinator_counts: dict[str, object] | None = None
    if coordinator is not None:
        snapshot = coordinator.status(current_run_id())
        claimed_task = snapshot["claimed_task"]
        active_claims = snapshot["active_claims"]
        coordinator_counts = {
            key: snapshot[key]
            for key in ("queued_tasks", "queued_integrations", "pending_publications")
        }
        coordinator.close()
    else:
        private_dir = claim_dir(workdir)
        if private_dir is not None:
            claimed_task, active_claims = ClaimStore(private_dir, owner_id(workdir)).summary()

    from .goal import read_goal

    active_goal = read_goal(workdir)

    if not verify:
        action = "configure verify with `looptight init`"
    elif workspace == "dirty":
        action = "review changes and run `looptight verify --json`"
    elif claimed_task:
        action = f"continue claimed task {claimed_task}"
    elif active_goal is not None:
        action = "run `looptight goal next` (a build goal is active)"
    else:
        action = "run `looptight next --json`"

    readiness = _readiness(
        workdir=workdir,
        verify=verify,
        workspace=workspace,
        config_tasks=config.tasks,
        agent=agent,
        fallback_action=action,
    )
    verifier_quality = _verifier_quality(verify)
    concurrency = _concurrency(
        workdir=workdir,
        workspace=workspace,
        active_claims=active_claims,
        coordinator_counts=coordinator_counts,
    )
    payload = {
        "schema_version": 1,
        "command": "status",
        "validation": "configured" if verify else "missing",
        "workspace": workspace,
        "claimed_task": claimed_task,
        "active_claims": active_claims,
        "next_action": action,
        "readiness": readiness,
        "verifier_quality": verifier_quality,
        "concurrency": concurrency,
        "coordination_scope": coordination_scope(workdir),
        "policy": _policy_summary(config),
    }
    if coordinator_counts is not None:
        payload["coordinator"] = coordinator_counts
    if active_goal is not None:
        payload["goal"] = {
            "vision": active_goal.vision,
            "iteration": active_goal.iteration,
            "continuous": active_goal.continuous,
        }

    from .idea_eval import score_status_next

    batch = score_status_next(workdir)
    idea_quality = (
        {
            "size": batch.size,
            "groundedness": round(batch.groundedness, 3),
            "flexibility": batch.flexibility,
            "bounded": batch.bounded,
        }
        if batch.size
        else None
    )
    if idea_quality is not None:
        payload["idea_quality"] = idea_quality

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        console.print(f"readiness: {readiness['tier']}")
        console.print(
            "readiness checks: "
            + " · ".join(
                f"{key} {value}" for key, value in readiness["checks"].items()
            )
        )
        console.print(f"readiness next: {readiness['next_remediation']}")
        console.print(f"validation: {payload['validation']}")
        if verify:
            console.print(f"verify: {verify}")
        console.print(
            f"verifier quality: {verifier_quality['classification']} — "
            f"{verifier_quality['risk']}"
        )
        console.print(f"concurrency: {concurrency['status']}")
        console.print(
            "concurrency checks: "
            + " · ".join(
                f"{key} {value}" for key, value in concurrency["checks"].items()
            )
        )
        console.print(f"concurrency next: {concurrency['next_remediation']}")
        console.print(f"workspace: {workspace}")
        owner = f" · yours: {claimed_task}" if claimed_task else ""
        console.print(f"claims: {active_claims} active{owner}")
        if coordinator_counts is not None:
            console.print(
                f"coordinator: {coordinator_counts['queued_tasks']} queued · "
                f"{coordinator_counts['queued_integrations']} integrations · "
                f"{coordinator_counts['pending_publications']} publications"
            )
        if active_goal is not None:
            console.print(
                f"goal: {active_goal.vision} (iteration {active_goal.iteration}"
                f"{', continuous' if active_goal.continuous else ''})"
            )
        if idea_quality is not None:
            console.print(
                f"idea quality: {idea_quality['size']} task(s) · "
                f"groundedness {idea_quality['groundedness']} · "
                f"areas {idea_quality['flexibility']} · "
                f"bounded {'yes' if idea_quality['bounded'] else 'no'}"
            )
        console.print(f"next: {action}")
        panel = render_state_panel(read_state(workdir))
        if panel:
            console.print(panel)
    return 0


def _readiness(
    *,
    workdir: Path,
    verify: str | None,
    workspace: str,
    config_tasks: tuple[str, ...],
    agent: str | None,
    fallback_action: str,
) -> dict[str, object]:
    checks = {
        "verify": "configured" if verify else "missing",
        "git": workspace,
        "coordinator": _coordinator_activation(workdir, workspace),
        "task_sources": _task_source_health(workdir, config_tasks),
        "agent": "available" if agent else "missing",
    }
    if checks["verify"] == "missing" or checks["git"] != "clean":
        tier = "unsafe"
    elif (
        # Migration state is not a readiness gate: the coordinator is already the
        # claim store. The coordinator check stays reported, not gating.
        checks["task_sources"] != "configured"
        or checks["agent"] != "available"
    ):
        tier = "partial"
    else:
        tier = "ready"
    return {
        "tier": tier,
        "checks": checks,
        "next_remediation": _readiness_remediation(checks, fallback_action),
    }


def _coordinator_activation(workdir: Path, workspace: str) -> str:
    # The SQLite coordinator is the claim store in any git repo: `next` leases
    # through it whether or not `migrate` has run. So "active" reflects the store
    # being in use, not the migrate marker (which only fences legacy file claims).
    if workspace == "not_git":
        return "not_git"
    if _git_common_dir(workdir) is None:
        return "unknown"
    return "active"


def _git_common_dir(workdir: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = workdir / common
    return common


def _task_source_health(workdir: Path, config_tasks: tuple[str, ...]) -> str:
    if config_tasks:
        return "configured"
    if (workdir / "docs" / "STATUS.md").is_file():
        return "configured"
    # Auto-discovered TODOs and skipped tests are looptight's primary task source,
    # so a repo with discoverable work is healthy even without a configured file.
    from .discovery import from_skipped_tests, from_todos

    if from_todos(workdir) or from_skipped_tests(workdir):
        return "configured"
    return "missing"


def _readiness_remediation(checks: dict[str, str], fallback_action: str) -> str:
    if checks["verify"] == "missing":
        return "run `looptight init`"
    if checks["git"] == "not_git":
        return "run inside a Git repository"
    if checks["git"] == "dirty":
        return "review changes and run `looptight verify --json`"
    if checks["task_sources"] == "missing":
        return "add grounded tasks or configure `tasks` in .looptight.toml"
    if checks["agent"] == "missing":
        return "install a supported agent CLI"
    return fallback_action


def _verifier_quality(command: str | None) -> dict[str, str]:
    if not command:
        return {
            "classification": "none",
            "risk": "No verifier is configured, so Looptight cannot gate changes.",
        }
    normalized = command.lower()
    # A pytest `-m "not integration"` / `not e2e` deselection EXCLUDES those markers,
    # so drop the negated clause before the substring scan — the command is a unit
    # run and must not be read as an integration/e2e verifier off the leftover word.
    scan = normalized.replace("not integration", "").replace("not e2e", "").replace("not playwright", "").replace("not cypress", "")
    # Strongest signal wins. A command that runs tests *and* a linter (e.g.
    # `pytest -q && ruff check`) is classified by its tests, not short-circuited
    # to lint-only — so lint-only is checked last, only when no test runner is present.
    if any(tool in scan for tool in ("playwright", "cypress")) or "e2e" in scan:
        return {
            "classification": "e2e",
            "risk": "End-to-end checks are strong for covered flows, but uncovered paths can still break.",
        }
    if "integration" in scan:
        return {
            "classification": "integration",
            "risk": "Integration checks cover connected components, but may not cover every user flow.",
        }
    if any(
        tool in normalized
        for tool in (
            "pytest", "unittest", "npm test", "pnpm test", "yarn test", "vitest", "jest",
            # The unambiguous single-runner test commands detect_verify auto-selects
            # (detect.py): a project on one of these gets `unit`, not `custom/unknown`,
            # so looptight does not call its own detected test command unknown. make/
            # just recipes are intentionally left to `custom/unknown` (arbitrary).
            "cargo test", "go test", "deno test", "mix test", "swift test", "dotnet test",
            "gradle test", "gradlew test", "mvn test", "mvnw test",
        )
    ):
        return {
            "classification": "unit",
            "risk": "Unit tests protect covered behavior, but integration and user-flow regressions can remain.",
        }
    if any(tool in normalized for tool in ("ruff", "flake8", "eslint", "prettier")):
        return {
            "classification": "lint-only",
            "risk": "This only protects style/static checks; behavior can still break.",
        }
    return {
        "classification": "custom/unknown",
        "risk": "Custom verifier; Looptight cannot infer what this command covers.",
    }


def _concurrency(
    *,
    workdir: Path,
    workspace: str,
    active_claims: int,
    coordinator_counts: dict[str, object] | None,
) -> dict[str, object]:
    coordinator = _coordinator_activation(workdir, workspace)
    claims = claim_dir(workdir)
    legacy_claims = bool(claims and has_live_claim(claims))
    queued_integrations = _count(coordinator_counts, "queued_integrations")
    pending_publications = _count(coordinator_counts, "pending_publications")
    checks: dict[str, object] = {
        "coordinator": coordinator,
        "legacy_claims": "live" if legacy_claims else "none",
        "active_leases": active_claims,
        "queued_integrations": queued_integrations,
        "pending_publications": pending_publications,
        "scope": "local-filesystem",
    }
    # Unsafe only when there is no process-safe store (outside Git) or live legacy
    # file claims race the coordinator. A plain git repo, where the coordinator is
    # the store, is safe even before `migrate` fences the (absent) legacy claims.
    if workspace == "not_git" or legacy_claims:
        status = "unsafe"
    elif active_claims or queued_integrations or pending_publications:
        status = "degraded"
    else:
        status = "safe"
    return {
        "status": status,
        "scope": "local-filesystem",
        "checks": checks,
        "next_remediation": _concurrency_remediation(
            workspace, legacy_claims, status
        ),
    }


def _count(counts: dict[str, object] | None, key: str) -> int:
    if counts is None:
        return 0
    value = counts.get(key, 0)
    return value if isinstance(value, int) else 0


def _concurrency_remediation(
    workspace: str, legacy_claims: bool, status: str
) -> str:
    if workspace == "not_git":
        return "run inside a Git repository"
    if legacy_claims:
        return "wait for legacy claims to expire or clear them, then run `looptight migrate`"
    if status == "degraded":
        return "wait for active coordinator work to drain"
    return "none"


def _policy_summary(config) -> dict[str, object]:
    return {
        "protected_paths": list(config.protected_paths),
        "no_direct_push": config.no_direct_push,
        "max_changed_files": config.max_changed_files,
        "allowed_verify_commands": list(config.allowed_verify_commands),
    }


def cmd_goal(args: argparse.Namespace, console: Console) -> int:
    """Set or run a vision-driven build goal. Makes no model call."""
    from .goal import Goal, clear_goal, goal_next, read_goal, run_done_check, write_goal

    workdir = Path.cwd()
    arg = args.arg

    if arg == "status" or arg is None:
        goal = read_goal(workdir)
        if args.json:
            # schema_version is part of the contract in both states; goal.as_dict()
            # also sets it (same value), so a present goal does not change it.
            payload: dict[str, object] = {
                "schema_version": 1, "command": "goal", "active": goal is not None,
            }
            if goal is not None:
                payload.update(goal.as_dict())
            print(json.dumps(payload, sort_keys=True))
        elif goal is None:
            console.print("no active goal")
        else:
            console.print(
                f"goal: {goal.vision} (iteration {goal.iteration}"
                f"{', continuous' if goal.continuous else ''}"
                f"{f', max {goal.max_iterations}' if goal.max_iterations else ''})"
            )
        return 0

    if arg == "clear":
        cleared = clear_goal(workdir)
        if args.json:
            print(json.dumps(
                {"schema_version": 1, "command": "goal", "active": False, "cleared": cleared},
                sort_keys=True,
            ))
        else:
            console.print("cleared the active goal" if cleared else "no active goal")
        return 0

    if arg == "next":
        decision = goal_next(workdir)
        if args.json:
            print(json.dumps(decision.as_dict(), sort_keys=True))
        elif decision.status == "no_goal":
            console.print("no active goal; set one with `looptight goal \"<vision>\"`")
        elif decision.status == "active":
            console.print(f"Iteration {decision.iteration}:")
            console.print(decision.directive["prompt"])
        else:
            console.print(f"goal {decision.status}" + (f" ({decision.reason})" if decision.reason else ""))
        return 0

    if arg == "check":
        # An exit-code predicate (for `/loop until: looptight goal check`), but --json
        # must still emit a machine verdict for parity with the other goal actions. The
        # exit code is unchanged so the shell-predicate use is unaffected either way.
        def _check_result(status: str, code: int) -> int:
            if args.json:
                print(json.dumps(
                    {"schema_version": 1, "command": "goal", "action": "check", "status": status},
                    sort_keys=True,
                ))
            return code

        goal = read_goal(workdir)
        if goal is None:
            if not args.json:
                console.print('[yellow]no active goal[/yellow] — set one with `looptight goal "<vision>"`.')
            return _check_result("no_goal", 1)
        if not goal.done_check:
            if not args.json:
                console.print(
                    "[yellow]this goal has no done-check[/yellow]; `goal check` cannot tell when "
                    'it is complete. Set one with `looptight goal "<vision>" --done "<command>"`.'
                )
            return _check_result("no_done_check", 1)
        done = run_done_check(workdir, goal.done_check)
        return _check_result("done" if done else "pending", 0 if done else 1)

    # Otherwise `arg` is a vision to set/activate. Validate before writing: a goal is stored
    # in Git, and a vacuous vision would persist misleading state and hand the host an empty
    # build directive. Both degrade cleanly (JSON envelope under --json) instead of a traceback.
    from .checkpoint import is_git_repo

    def _set_error(code: str, human: str) -> int:
        if args.json:
            print(json.dumps(
                {"schema_version": 1, "command": "goal", "status": "error", "error": code},
                sort_keys=True,
            ))
        else:
            console.print(f"[red]{human}[/red]")
        return 2

    if not is_git_repo(workdir):
        return _set_error(
            "not_git",
            "run `looptight goal` inside a Git repository; it stores the goal in Git.",
        )
    if not arg.strip():
        return _set_error(
            "empty_vision",
            'a goal needs a non-empty vision; set one with `looptight goal "<vision>"`.',
        )
    goal = Goal(
        vision=arg,
        done_check=args.done_check,
        continuous=args.continuous,
        max_iterations=args.max_iterations,
    )
    write_goal(workdir, goal)
    if args.json:
        payload = {"schema_version": 1, "command": "goal", "active": True}
        payload.update(goal.as_dict())
        print(json.dumps(payload, sort_keys=True))
        return 0
    console.print(f"goal set: {arg}")
    if args.continuous:
        console.print(_goal_driver_recipe(workdir))
    return 0


def _goal_driver_recipe(workdir: Path) -> str:
    """Hands-off driver recipe for the active goal, tailored to the detected agent."""
    lines = ["Run hands-off until the goal's done-check passes or usage is spent:"]
    if detect_agent() == "claude":
        lines.append("  Claude Code:  /loop until: looptight goal check")
    lines.append(
        "  Any agent:    repeat `looptight goal next` -> build -> `looptight verify`"
        " -> commit, until `looptight goal check` passes"
    )
    return "\n".join(lines)
