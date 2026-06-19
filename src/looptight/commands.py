"""CLI command handlers.

The ``cmd_*`` functions dispatched by :mod:`looptight.cli`. They live in their
own module so ``cli.py`` stays a thin parser + dispatcher (file-size hygiene).
Each takes the parsed args and a rich ``Console`` and returns an exit code.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .adapters import available_adapter_names, get_adapter
from .checkpoint import is_git_repo
from .config import Config, load_config, write_config
from .detect import detect_agent, detect_verify
from .improve import ImproveStopReason, run_improve
from .lessons import LessonStore
from .loop import run_loop
from .summary import render_rich
from .types import StopReason
from .verify import run_verify


def cmd_init(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
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
    console.print()
    console.print('Then: [bold]looptight "fix the failing tests"[/bold]')
    return 0


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    config = load_config().merged(
        agent=args.agent,
        verify=args.verify,
        max_iterations=args.max_iterations,
        patience=args.patience,
        budget_usd=args.budget,
        reflect=False if args.no_reflect else None,
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
        console.print('  looptight init   (auto-detects)   or   looptight run "..." --verify "pytest -q"')
        return 2

    use_native = config.native and adapter.supports_native_loop
    if config.native and not adapter.supports_native_loop:
        console.print(f"[yellow]{agent_name} has no native loop; supplying the loop instead.[/yellow]")

    store = LessonStore(adapter.memory_file(workdir))
    verb = "driving native loop" if use_native else "supplying loop"
    console.print(
        f"[bold]looptight[/bold] · agent: [cyan]{agent_name}[/cyan] ({verb}) · "
        f"verify: [cyan]{config.verify}[/cyan] · budget: ${config.budget_usd:.2f}"
    )
    console.print()

    def on_iteration(record) -> None:  # live counter (D2)
        style = "green" if record.verify.passed else "red"
        console.print(
            f"iteration {record.number} → verify: [{style}]{record.verify.short()}[/{style}]"
            f"   [dim]${record.cost_usd:.2f}[/dim]"
        )

    try:
        result = run_loop(
            args.goal, adapter, config, workdir, native=use_native, store=store, on_iteration=on_iteration
        )
    except NotImplementedError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return 3

    console.print()
    render_rich(result, console)
    return 0 if result.stop_reason is StopReason.SUCCESS else 1


def cmd_improve(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    config = load_config().merged(
        agent=args.agent,
        verify=args.verify,
        max_iterations=args.max_iterations,
        patience=args.patience,
        reflect=False if args.no_reflect else None,
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
        console.print("[red]No verify command.[/red] No verify, no improve loop.")
        return 2

    use_native = config.native and adapter.supports_native_loop
    if args.budget is not None and not adapter.reports_cost_usd:
        console.print(
            f"[yellow]{agent_name} does not report USD cost; looptight cannot enforce the "
            "session budget and will use the provider's limit.[/yellow]"
        )

    store = LessonStore(adapter.memory_file(workdir))

    def on_iteration(record) -> None:
        style = "green" if record.verify.passed else "red"
        console.print(
            f"  iteration {record.number} → verify: [{style}]{record.verify.short()}[/{style}]"
            f"   [dim]${record.cost_usd:.2f}[/dim]"
        )

    def run_task(goal, checkpointer):
        return run_loop(
            goal,
            adapter,
            config,
            workdir,
            native=use_native,
            checkpointer=checkpointer,
            store=store,
            on_iteration=on_iteration,
        )

    console.print(
        f"[bold]looptight improve[/bold] · agent: [cyan]{agent_name}[/cyan] · "
        f"verify: [cyan]{config.verify}[/cyan] · "
        f"session budget: {'provider limit' if args.budget is None else f'${args.budget:.2f}'}"
    )
    result = run_improve(
        workdir,
        run_task,
        session_budget_usd=args.budget if adapter.reports_cost_usd else None,
        push=args.push,
        on_event=lambda message: console.print(f"[bold]{message}[/bold]"),
    )
    console.print(
        f"stopped: {result.stop_reason.value.replace('_', ' ')} · "
        f"{result.tasks_attempted} task(s) · {result.commits} commit(s) · "
        f"${result.total_cost_usd:.2f} reported"
    )
    if result.error:
        console.print(f"[yellow]{result.error}[/yellow]")
    return {
        ImproveStopReason.SESSION_BUDGET: 0,
        ImproveStopReason.PROVIDER_STOP: 1,
        ImproveStopReason.INTERRUPTED: 130,
        ImproveStopReason.GIT_ERROR: 2,
    }[result.stop_reason]


def cmd_verify(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    command = args.verify or load_config().verify or detect_verify(workdir)
    if not command:
        console.print("[red]No verify command found.[/red] Pass --verify or run `looptight init`.")
        return 2
    result = run_verify(command, workdir)
    style = "green" if result.passed else "red"
    console.print(f"verify: [{style}]{result.short()}[/{style}] (exit {result.exit_code})")
    return 0 if result.passed else 1


def cmd_lessons(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    agent_name = args.agent or detect_agent() or "claude"
    store = LessonStore(get_adapter(agent_name).memory_file(workdir))

    if args.clear:
        removed = store.prune()
        console.print(f"removed {removed} lesson(s) from {store.memory_file.name}")
        return 0
    if args.prune:
        removed = store.prune(contains=args.prune)
        console.print(f"removed {removed} lesson(s) matching '{args.prune}'")
        return 0

    lessons = store.list()
    if not lessons:
        console.print("No lessons yet. They'll appear here after a failed-then-fixed run.")
        return 0
    console.print(f"[bold]{len(lessons)} lesson(s)[/bold] in {store.memory_file.name}:")
    for lesson in lessons:
        console.print(f"  {lesson.render()}")
    return 0


def cmd_doctor(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    config = load_config()
    agent = config.agent or detect_agent()
    verify = config.verify or detect_verify(workdir)

    console.print("[bold]looptight doctor[/bold]")
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
    return 0


def cmd_propose(args: argparse.Namespace, console: Console) -> int:
    from .propose import propose

    candidates = propose(Path.cwd(), limit=args.limit)
    if args.json:
        import json

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
        "highest-value actionable task, runs it through[/dim] [bold]looptight run "
        '"<task>"[/bold][dim], reviews and verifies the result, then commits and pushes a '
        "coherent change to main.[/dim]"
    )
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
