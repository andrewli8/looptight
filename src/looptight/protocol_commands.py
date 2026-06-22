"""Machine-facing validation and task protocol command handlers."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .claims import ClaimStore, claim_dir, owner_id
from .config import ConfigError, load_config
from .console import Console
from .coordinator import Coordinator, current_run_id
from .detect import detect_verify
from .verify import run_verify


def cmd_verify(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    try:
        command = args.verify or load_config().verify or detect_verify(workdir)
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
    result = run_verify(command, workdir)
    if args.json:
        _print_verify_json(
            status=result.status,
            exit_code=result.exit_code,
            score=result.score,
            duration_ms=round(result.duration_s * 1000, 3),
            output=result.output,
            error=result.error,
        )
        return _verify_exit_code(result.status)
    style = "green" if result.passed else "red"
    console.print(f"verify: [{style}]{result.short()}[/{style}] (exit {result.exit_code})")
    return _verify_exit_code(result.status)


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
) -> None:
    """Emit the v1 verifier contract without terminal styling or wrapping."""
    print(
        json.dumps(
            {
                "schema_version": 1,
                "command": "verify",
                "status": status,
                "exit_code": exit_code,
                "score": score,
                "duration_ms": duration_ms,
                "output": output,
                "error": error,
            },
            sort_keys=True,
        )
    )


def cmd_propose(args: argparse.Namespace, console: Console) -> int:
    from .propose import propose

    candidates = propose(Path.cwd(), limit=args.limit)
    if args.json:
        print(json.dumps([c.__dict__ for c in candidates], indent=2))
        return 0

    if not candidates:
        console.print("No candidate tasks found from repo signals (clean tree).")
        return 0

    console.print(
        f"[bold]{len(candidates)} candidate task(s)[/bold] "
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
    return 0


def cmd_next(args: argparse.Namespace, console: Console) -> int:
    """Print the single next task for the current session to execute."""
    from .tasks import next_task

    idea_generation = load_config().idea_generation and not args.no_ideas
    result = next_task(Path.cwd(), idea_generation=idea_generation)
    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
    elif result.status == "error":
        print(f"ERROR: {result.error}")
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
        print(result.task["goal"])
        acceptance = result.task.get("acceptance")
        if acceptance:
            print(f"Acceptance: {acceptance}")
    return 2 if result.status == "error" else 0


def cmd_status(args: argparse.Namespace, console: Console) -> int:
    """Report safety state without running validation or claiming work."""
    workdir = Path.cwd()
    verify = load_config().verify or detect_verify(workdir)
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
    if coordinator is not None:
        claimed_task, active_claims = coordinator.summary(current_run_id())
        coordinator.close()
    else:
        private_dir = claim_dir(workdir)
        if private_dir is not None:
            claimed_task, active_claims = ClaimStore(private_dir, owner_id(workdir)).summary()

    if not verify:
        action = "configure verify with `looptight init`"
    elif workspace == "dirty":
        action = "review changes and run `looptight verify --json`"
    elif claimed_task:
        action = f"continue claimed task {claimed_task}"
    else:
        action = "run `looptight next --json`"

    payload = {
        "schema_version": 1,
        "command": "status",
        "validation": "configured" if verify else "missing",
        "workspace": workspace,
        "claimed_task": claimed_task,
        "active_claims": active_claims,
        "next_action": action,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        console.print(f"validation: {payload['validation']}")
        if verify:
            console.print(f"verify: {verify}")
        console.print(f"workspace: {workspace}")
        owner = f" · yours: {claimed_task}" if claimed_task else ""
        console.print(f"claims: {active_claims} active{owner}")
        console.print(f"next: {action}")
    return 0
