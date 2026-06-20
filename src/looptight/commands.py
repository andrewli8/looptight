"""CLI command handlers.

The ``cmd_*`` functions dispatched by :mod:`looptight.cli`. They live in their
own module so ``cli.py`` stays a thin parser + dispatcher (file-size hygiene).
Each takes the parsed args and a rich ``Console`` and returns an exit code.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .adapters import available_adapter_names, get_adapter
from .checkpoint import is_git_repo
from .claims import ClaimStore, claim_dir, owner_id
from .config import CONFIG_NAME, Config, ConfigError, find_config, load_config, write_config
from .console import Console
from .detect import detect_agent, detect_verify
from .integration import install_session_instructions
from .loop import run_loop
from .summary import render_rich
from .types import StopReason
from .verify import run_verify


def cmd_init(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    config_exists = (workdir / CONFIG_NAME).is_file()
    if config_exists:
        console.print(
            f"[yellow]{CONFIG_NAME} already exists[/yellow] — leaving it untouched. "
            "Edit it, or delete it to re-init."
        )
    else:
        verify = args.verify or detect_verify(workdir)
        agent = args.agent or detect_agent()
        config = Config(verify=verify, agent=agent)
        path = write_config(config, workdir)

        console.print(f"[green]wrote[/green] {path.name}")
        console.print()
        console.print("[bold]The one thing to know: `verify`.[/bold]")
        console.print("`verify` is the command that decides pass/fail. No verify, no loop.")
        if verify:
            console.print(f"Detected: [cyan]{verify}[/cyan]. Edit {path.name} if that's wrong.")
        else:
            console.print("[yellow]Could not detect a test command — set `verify` in the config.[/yellow]")
        if agent:
            console.print(f"Agent: [cyan]{agent}[/cyan] (auto-detected).")
        else:
            console.print("[yellow]No coding agent found on PATH (claude / codex / opencode).[/yellow]")

    if args.integrate:
        changed = install_session_instructions(workdir)
        state = "installed" if changed else "already installed"
        console.print(f"[green]{state}[/green] session loop for Codex, Claude Code, and OpenCode")
    elif not config_exists:
        console.print()
        console.print("For the native current-session loop: [bold]looptight init --integrate[/bold]")
    return 0


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    if not args.headless:
        console.print(
            "[red]run launches an agent child process.[/red] Pass --headless explicitly, "
            "or use `looptight init --integrate` for the current-session loop."
        )
        return 2
    workdir = Path.cwd()
    config = load_config().merged(
        agent=args.agent,
        verify=args.verify,
        max_iterations=args.max_iterations,
        patience=args.patience,
        native=True if args.native else None,
    )

    agent_name = config.agent or detect_agent()
    if not agent_name:
        console.print("[red]No coding agent found on PATH.[/red] Install claude, codex, or opencode.")
        return 2
    adapter = get_adapter(agent_name)

    if not config.verify:
        config = config.merged(verify=detect_verify(workdir))
    if not config.verify:
        console.print("[red]No verify command.[/red] No verify, no loop — set one:")
        console.print('  looptight init   or   looptight run --headless "..." --verify "pytest -q"')
        return 2

    use_native = config.native and adapter.supports_native_loop
    if config.native and not adapter.supports_native_loop:
        console.print(f"[yellow]{agent_name} has no native loop; supplying the loop instead.[/yellow]")

    verb = "driving native loop" if use_native else "supplying loop"
    console.print(
        f"[bold]looptight[/bold] · agent: [cyan]{agent_name}[/cyan] ({verb}) · "
        f"verify: [cyan]{config.verify}[/cyan]"
    )
    console.print()

    def on_iteration(record) -> None:  # live counter (D2)
        style = "green" if record.verify.passed else "red"
        console.print(
            f"iteration {record.number} → verify: [{style}]{record.verify.short()}[/{style}]"
        )

    try:
        result = run_loop(
            args.goal, adapter, config, workdir, native=use_native, on_iteration=on_iteration
        )
    except NotImplementedError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return 3

    console.print()
    render_rich(result, console)
    return 0 if result.stop_reason is StopReason.SUCCESS else 1


def cmd_improve(args: argparse.Namespace, console: Console) -> int:
    console.print(
        "[yellow]improve is deprecated and no longer launches agents.[/yellow] "
        "Use `looptight init --integrate`, then `next`, `verify`, and `status` "
        "inside the current agent session."
    )
    return 2


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


def cmd_doctor(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    config = load_config()
    agent = config.agent or detect_agent()
    verify = config.verify or detect_verify(workdir)

    config_path = find_config(workdir)
    console.print("[bold]looptight doctor[/bold]")
    console.print(
        f"  config: {config_path}" if config_path else "  config: none (using defaults)"
    )
    console.print(f"  agent (detected): {agent or '[red]none on PATH[/red]'}")
    console.print(f"  verify (detected): {verify or '[yellow]none[/yellow]'}")
    console.print(f"  git checkpoints: {'on' if is_git_repo(workdir) else '[yellow]off (not a git repo)[/yellow]'}")
    console.print("  adapters:")
    for name in available_adapter_names():
        adapter = get_adapter(name)
        status = "available" if adapter.is_available() else "not installed"
        loop = "supply + native loop (--native)" if adapter.supports_native_loop else "supply"
        console.print(f"    - {name}: {loop}, {status}")
    return 0


def cmd_revert(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    if not is_git_repo(workdir):
        console.print("[yellow]Not a git repo — nothing to revert.[/yellow]")
        return 1
    if not args.yes:
        console.print("This discards uncommitted changes (restores tracked files to HEAD).")
        console.print("Re-run with [bold]--yes[/bold] to confirm.")
        return 0
    import subprocess

    try:
        result = subprocess.run(
            ["git", "checkout", "HEAD", "--", "."], cwd=str(workdir), check=False
        )
    except OSError as exc:
        console.print(f"[red]error:[/red] could not run git checkout: {exc}")
        return 1
    if result.returncode != 0:
        console.print("[red]error:[/red] git checkout failed; restore not confirmed. Inspect the working tree.")
        return 1
    console.print("[green]reverted[/green] tracked files to HEAD.")
    # revert is tracked-only by design; tell the user about any untracked files
    # the agent created so the leftover state isn't a surprise. This is purely
    # informational — never let it crash a revert that already succeeded.
    try:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        leftovers = untracked.stdout.splitlines() if untracked.returncode == 0 else []
    except OSError:
        leftovers = []
    if leftovers:
        console.print(
            f"[yellow]{len(leftovers)} untracked file(s) left in place[/yellow] — revert only "
            "touches tracked files; remove them with `git clean -fd` if unwanted."
        )
    return 0


def cmd_propose(args: argparse.Namespace, console: Console) -> int:
    from .propose import propose

    candidates = propose(Path.cwd(), limit=args.limit)
    if args.json:
        print(json.dumps([c.__dict__ for c in candidates], indent=2))
        return 0

    if not candidates:
        console.print("No candidate tasks found from repo signals (clean tree).")
        return 0

    console.print(f"[bold]{len(candidates)} candidate task(s)[/bold] (ranked; pick what to run):")
    console.print()
    for i, c in enumerate(candidates, 1):
        where = f" [dim]{c.location}[/dim]" if c.location else ""
        console.print(f"  {i}. [cyan]{c.source}[/cyan]  {c.title}{where}")
    console.print()
    console.print(
        "[dim]Ranking is a source-priority heuristic. The operating agent selects the "
        "highest-value actionable task in the current session, validates it with[/dim] "
        "[bold]looptight verify[/bold][dim], then commits and pushes a coherent change.[/dim]"
    )
    return 0


def cmd_next(args: argparse.Namespace, console: Console) -> int:
    """Print the single next task to work on, for the current session to execute.

    The in-session driver: run `looptight next`, do the task on this session's
    tokens, gate with `looptight verify`, commit — no spawned `claude -p`. Plain
    stdout so it's easy to capture/script."""
    from .tasks import next_task

    result = next_task(Path.cwd())
    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
    elif result.status == "no_work":
        print("NO_WORK")
    else:
        assert result.task is not None
        print(result.task["goal"])
    return 0


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
    workspace = "not_git" if git is None or git.returncode != 0 else (
        "dirty" if git.stdout.strip() else "clean"
    )

    private_dir = claim_dir(workdir)
    claimed_task = None
    active_claims = 0
    if private_dir is not None:
        claimed_task, active_claims = ClaimStore(
            private_dir, owner_id(workdir)
        ).summary()

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
        console.print(f"workspace: {workspace}")
        console.print(f"claims: {active_claims} active" + (f" · yours: {claimed_task}" if claimed_task else ""))
        console.print(f"next: {action}")
    return 0


def cmd_swarm(args: argparse.Namespace, console: Console) -> int:
    """Launch or stop a swarm of agent sessions across isolated git worktrees.

    `up` provisions N worktrees (one per worker, for write isolation + a distinct
    claim identity) and launches the configured agent CLI in each — running on the
    CLI's existing auth (subscription if logged in). Workers coordinate lock-free
    through looptight's shared claim store, so no two take the same task."""
    from .swarm import swarm_down, swarm_up

    workdir = Path.cwd()
    if not is_git_repo(workdir):
        console.print("[red]swarm requires a Git repository.[/red]")
        return 2
    base = Path(args.dir) if getattr(args, "dir", None) else None

    if args.swarm_command == "down":
        removed = swarm_down(workdir, base_dir=base)
        console.print(f"removed {len(removed)} swarm worktree(s)")
        return 0
    if args.swarm_command != "up":
        console.print("usage: looptight swarm {up|down}")
        return 2

    agent = args.agent or detect_agent()
    if not agent:
        console.print(
            "[red]No coding agent found on PATH.[/red] Install claude, codex, or "
            "opencode, or pass --agent."
        )
        return 2
    if not get_adapter(agent).is_available():
        console.print(f"[red]{agent} CLI is not available on PATH.[/red]")
        return 2

    result = swarm_up(workdir, args.workers, agent, base_dir=base)
    for spec in result.launched:
        console.print(f"[green]worker {spec.index}[/green] · {spec.branch} · {spec.worktree}")
    for err in result.errors:
        console.print(f"[yellow]{err}[/yellow]")
    if not result.launched:
        console.print("[red]no workers launched.[/red]")
        return 1
    console.print()
    console.print(
        f"launched {len(result.launched)} {agent} session(s) on the CLI's existing "
        "auth (subscription if logged in there)."
    )
    console.print("they coordinate via looptight claims — no two take the same task.")
    console.print("monitor: [bold]looptight status[/bold] · logs: looptight-swarm.log in each worktree")
    console.print("stop:    [bold]looptight swarm down[/bold]")
    return 0


def cmd_hook(args: argparse.Namespace, console: Console) -> int:
    """Claude Code Stop-hook entry point. Reads the event on stdin, and prints a
    decision JSON to stdout only when it wants Claude to keep going. Stdout has to
    stay clean for Claude to parse, so this path never uses the rich Console."""
    from .hook import run_hook

    output, code = run_hook(sys.stdin.read())
    if output:
        sys.stdout.write(output + "\n")
    return code


def cmd_install_hook(args: argparse.Namespace, console: Console) -> int:
    from .settings import install, project_settings_path, uninstall, user_settings_path

    path = project_settings_path(Path.cwd()) if args.project else user_settings_path()
    try:
        if args.uninstall:
            removed = uninstall(path)
            console.print(f"removed {removed} looptight hook(s) from {path}")
            return 0
        added = install(path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    if added:
        console.print(f"[green]installed[/green] the looptight Stop hook in {path}")
    else:
        console.print(f"already installed in {path}")
    console.print()
    console.print("The hook stays dormant until a repo opts in. In a project you want")
    console.print("auto-looping, set [cyan]hook = true[/cyan] in its .looptight.toml.")
    return 0
