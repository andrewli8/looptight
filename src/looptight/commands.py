"""Human-facing CLI handlers and stable exports for protocol handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapters import available_adapter_names, get_adapter
from .checkpoint import is_git_repo
from .config import CONFIG_NAME, Config, find_config, load_config, write_config
from .console import Console
from .detect import detect_agent, detect_verify
from .integration import install_session_instructions
from .loop import run_loop
from .protocol_commands import (
    cmd_next,
    cmd_propose,
    cmd_status,
    cmd_verify,
)
from .summary import render_rich
from .types import StopReason

__all__ = [
    "cmd_doctor",
    "cmd_hook",
    "cmd_improve",
    "cmd_init",
    "cmd_install_hook",
    "cmd_next",
    "cmd_propose",
    "cmd_revert",
    "cmd_run",
    "cmd_status",
    "cmd_verify",
]


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


def cmd_hook(args: argparse.Namespace, console: Console) -> int:
    """Claude Code Stop-hook entry point. Reads the event on stdin, and prints a
    decision JSON to stdout only when it wants Claude to keep going. Stdout has to
    stay clean for Claude to parse, so this path never uses the Console."""
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
