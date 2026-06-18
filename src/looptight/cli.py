"""Command-line interface.

The surface is deliberately tiny (A3 — one concept to learn). The default verb
is ``run``, so ``looptight "fix the failing tests"`` just works. Everything else
(``init``, ``verify``, ``lessons``, ``doctor``, ``revert``) supports that one
path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .adapters import available_adapter_names, get_adapter
from .checkpoint import Checkpointer, is_git_repo
from .config import load_config, write_config, Config
from .detect import KNOWN_AGENTS, detect_agent, detect_verify
from .lessons import LessonStore
from .loop import run_loop
from .summary import render_rich
from .types import StopReason
from .verify import run_verify

_COMMANDS = {"init", "run", "verify", "lessons", "doctor", "revert", "hook", "install-hook"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="looptight",
        description="Your coding agent on autopilot — across agents — that gets smarter every run.",
    )
    parser.add_argument("--version", action="version", version=f"looptight {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="write a minimal .looptight.toml and explain `verify`")
    p_init.add_argument("--verify", help="verify command (auto-detected if omitted)")
    p_init.add_argument("--agent", choices=KNOWN_AGENTS, help="pin an agent (auto-detected if omitted)")

    p_run = sub.add_parser("run", help="run your agent until verify passes")
    p_run.add_argument("goal", help="what you want done, in plain language")
    _add_run_flags(p_run)

    p_verify = sub.add_parser("verify", help="run the verify command once and report")
    p_verify.add_argument("--verify", help="override the verify command")

    p_lessons = sub.add_parser("lessons", help="show or prune the lessons looptight has learned")
    p_lessons.add_argument("--agent", choices=KNOWN_AGENTS, help="which agent's memory file to read")
    p_lessons.add_argument("--clear", action="store_true", help="remove all lessons")
    p_lessons.add_argument("--prune", metavar="TEXT", help="remove lessons whose text contains TEXT")

    sub.add_parser("doctor", help="show the detected agent, verify command, and adapter status")

    p_revert = sub.add_parser("revert", help="undo the agent's uncommitted edits (restore to HEAD)")
    p_revert.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    sub.add_parser("hook", help="Claude Code Stop-hook handler (reads the hook event on stdin)")

    p_install = sub.add_parser(
        "install-hook", help="register the Stop-hook auto-loop in Claude Code's settings.json"
    )
    p_install.add_argument(
        "--project", action="store_true", help="install into ./.claude/settings.json instead of the user file"
    )
    p_install.add_argument("--uninstall", action="store_true", help="remove the looptight Stop hook instead")

    return parser


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", choices=KNOWN_AGENTS, help="agent to use (auto-detected if omitted)")
    parser.add_argument("--verify", help="verify command (auto-detected if omitted)")
    parser.add_argument("--max-iterations", type=int, help="hard iteration cap")
    parser.add_argument(
        "--budget",
        type=float,
        help="cost ceiling in USD — the only way to raise it above the safe default",
    )
    parser.add_argument("--no-reflect", action="store_true", help="do not write lessons on failure")
    parser.add_argument(
        "--native",
        action="store_true",
        help="drive the agent's own loop where it has one (e.g. Claude /goal); verify still gates",
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Default verb: a bare goal string means `run` (A2/A3 ergonomics).
    if argv and not argv[0].startswith("-") and argv[0] not in _COMMANDS:
        argv = ["run", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if not args.command:
        parser.print_help()
        return 0

    handler = {
        "init": cmd_init,
        "run": cmd_run,
        "verify": cmd_verify,
        "lessons": cmd_lessons,
        "doctor": cmd_doctor,
        "revert": cmd_revert,
        "hook": cmd_hook,
        "install-hook": cmd_install_hook,
    }[args.command]
    return handler(args, console)


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
    checkpointer = Checkpointer(workdir)
    import subprocess

    subprocess.run(["git", "checkout", "HEAD", "--", "."], cwd=str(workdir), check=False)
    console.print("[green]reverted[/green] tracked files to HEAD.")
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
