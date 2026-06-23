from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .console import Console
from .commands import (
    cmd_daemon,
    cmd_doctor,
    cmd_hook,
    cmd_improve,
    cmd_init,
    cmd_install_hook,
    cmd_migrate,
    cmd_next,
    cmd_propose,
    cmd_revert,
    cmd_run,
    cmd_status,
    cmd_swarm,
    cmd_verify,
)
from .config import ConfigError
from .detect import KNOWN_AGENTS
from .ui import serve_ui

_COMMANDS = {
    "init",
    "run",
    "improve",
    "verify",
    "doctor",
    "revert",
    "hook",
    "install-hook",
    "propose",
    "next",
    "status",
    "swarm",
    "daemon",
    "migrate",
    "ui",
}


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _port(value: str) -> int:
    parsed = _non_negative_int(value)
    if parsed > 65535:
        raise argparse.ArgumentTypeError("must be between 0 and 65535")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="looptight",
        description="A portable task and validation loop for native coding-agent sessions.",
    )
    parser.add_argument("--version", action="version", version=f"looptight {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="write a minimal .looptight.toml and explain `verify`")
    p_init.add_argument("--verify", help="verify command (auto-detected if omitted)")
    p_init.add_argument("--agent", choices=KNOWN_AGENTS, help="pin an agent (auto-detected if omitted)")
    p_init.add_argument(
        "--integrate",
        action="store_true",
        help="install the session loop in AGENTS.md and CLAUDE.md",
    )

    p_run = sub.add_parser("run", help="explicit headless compatibility loop")
    p_run.add_argument("goal", help="what you want done, in plain language")
    _add_run_flags(p_run)

    p_improve = sub.add_parser(
        "improve", help="deprecated; migrate to the native-session loop"
    )
    _add_improve_flags(p_improve)

    p_verify = sub.add_parser("verify", help="run the verify command once and report")
    p_verify.add_argument("--verify", help="override the verify command")
    p_verify.add_argument("--json", action="store_true", help="emit the versioned verdict as JSON")

    sub.add_parser("doctor", help="show the detected agent, verify command, and adapter status")

    p_revert = sub.add_parser("revert", help="undo the agent's uncommitted edits (restore to HEAD)")
    p_revert.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    p_propose = sub.add_parser(
        "propose", help="rank grounded repository tasks without model or network calls"
    )
    p_propose.add_argument("--json", action="store_true", help="emit the ranked candidates as JSON")
    p_propose.add_argument(
        "--limit", type=_non_negative_int, default=10, help="max candidates to show (default 10)"
    )

    p_next = sub.add_parser(
        "next",
        help="return one grounded task or NO_WORK for the current agent session",
    )
    p_next.add_argument("--json", action="store_true", help="emit the versioned task decision as JSON")
    p_next.add_argument(
        "--no-ideas",
        action="store_true",
        help="on an empty queue, report no_work instead of directing idea generation",
    )

    p_status = sub.add_parser("status", help="show validation readiness and the next safe action")
    p_status.add_argument("--json", action="store_true", help="emit the versioned status as JSON")

    p_migrate = sub.add_parser(
        "migrate", help="activate the repository coordinator (migrate from legacy claims)"
    )
    p_migrate.add_argument("--json", action="store_true", help="emit the activation result as JSON")

    p_swarm = sub.add_parser("swarm", help="run isolated headless workers from the grounded queue")
    p_swarm.add_argument("--headless", action="store_true", help="explicitly allow agent child processes")
    p_swarm.add_argument("--agent", choices=KNOWN_AGENTS, help="agent CLI for every worker")
    p_swarm.add_argument("--model", help="provider model for every spawned worker (e.g. opus)")
    p_swarm.add_argument("--workers", type=_positive_int, default=4, help="concurrent workers (1-50)")
    p_swarm.add_argument("--verify", help="override the project verify command")
    p_swarm.add_argument("--max-iterations", type=_positive_int, help="iteration cap per worker")
    p_swarm.add_argument(
        "--worker-timeout",
        type=_positive_float,
        default=3600.0,
        help="seconds allowed for each provider invocation (default 3600)",
    )
    p_swarm.add_argument("--push", action="store_true", help="push integrated commits after the swarm")
    p_swarm.add_argument(
        "--continuous",
        action="store_true",
        help="repeat swarm rounds and use the agent to plan when the grounded queue is empty",
    )
    p_swarm.add_argument(
        "--max-rounds",
        type=_non_negative_int,
        default=0,
        help="continuous swarm round cap (0 = until no work, failure, or interruption)",
    )
    p_swarm.add_argument(
        "--resume-on-limit",
        action="store_true",
        help="continuous: wait out a provider usage/rate limit and resume instead of stopping",
    )
    p_swarm.add_argument(
        "--limit-backoff-seconds",
        type=_positive_float,
        default=30.0,
        help="continuous: initial back-off when the provider names no reset (default 30)",
    )
    p_swarm.add_argument(
        "--limit-max-wait-seconds",
        type=_positive_float,
        default=3600.0,
        help="continuous: cap on a single usage-limit wait before re-polling (default 3600)",
    )
    p_swarm.add_argument(
        "--no-ideas",
        action="store_true",
        help="continuous: stop when the queue empties instead of planning new grounded tasks",
    )
    p_swarm.add_argument("--json", action="store_true", help="emit the versioned swarm result as JSON")

    p_daemon = sub.add_parser(
        "daemon",
        help="run a persistent continuous swarm that restarts forever (true 24/7 operation)",
    )
    p_daemon.add_argument("--headless", action="store_true", help="explicitly allow agent child processes")
    p_daemon.add_argument("--agent", choices=KNOWN_AGENTS, help="agent CLI for every worker")
    p_daemon.add_argument("--model", help="provider model for every spawned worker (e.g. opus)")
    p_daemon.add_argument("--workers", type=_positive_int, default=4, help="concurrent workers (1-50)")
    p_daemon.add_argument("--verify", help="override the project verify command")
    p_daemon.add_argument("--max-iterations", type=_positive_int, help="iteration cap per worker")
    p_daemon.add_argument(
        "--worker-timeout",
        type=_positive_float,
        default=3600.0,
        help="seconds allowed for each provider invocation (default 3600)",
    )
    p_daemon.add_argument("--push", action="store_true", help="push integrated commits to main each cycle")
    p_daemon.add_argument(
        "--no-ideas",
        action="store_true",
        help="do not generate grounded tasks when the queue empties (idle instead)",
    )
    p_daemon.add_argument(
        "--no-resume-on-limit",
        action="store_true",
        help="treat a provider usage limit as a fault instead of waiting it out",
    )
    p_daemon.add_argument(
        "--idle-sleep",
        type=_positive_float,
        default=600.0,
        help="seconds to wait before re-polling when there is nothing to build (default 600)",
    )
    p_daemon.add_argument(
        "--fault-backoff",
        type=_positive_float,
        default=30.0,
        help="initial back-off (s) after a genuine fault; doubles each consecutive fault (default 30)",
    )
    p_daemon.add_argument(
        "--fault-max-backoff",
        type=_positive_float,
        default=1800.0,
        help="cap (s) on the fault back-off so recovery latency stays bounded (default 1800)",
    )
    p_daemon.add_argument(
        "--max-idle-rounds",
        type=_positive_int,
        default=3,
        help="planning rounds with no merged progress before a cycle ends and the daemon polls (default 3)",
    )
    p_daemon.add_argument(
        "--max-cycles",
        type=_non_negative_int,
        default=0,
        help="stop after this many supervised cycles (0 = run forever)",
    )
    p_daemon.add_argument(
        "--on-fault",
        metavar="CMD",
        help="run CMD with a JSON fault payload on stdin when a cycle faults (optional)",
    )

    p_ui = sub.add_parser("ui", help="serve the read-only swarm view on localhost")
    p_ui.add_argument("--port", type=_port, default=8765, help="loopback port (default 8765)")

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
    parser.add_argument(
        "--headless",
        action="store_true",
        help="explicitly allow launching the configured agent CLI as a child process",
    )
    parser.add_argument("--agent", choices=KNOWN_AGENTS, help="agent to use (auto-detected if omitted)")
    parser.add_argument("--model", help="provider model for the spawned session (e.g. opus)")
    parser.add_argument("--verify", help="verify command (auto-detected if omitted)")
    parser.add_argument("--max-iterations", type=_positive_int, help="hard iteration cap")
    parser.add_argument(
        "--patience",
        type=int,
        help="stop early after N iterations with no measurable progress (0 = off)",
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="drive the agent's own loop where it has one (e.g. Claude /goal); verify still gates",
    )
    parser.add_argument(
        "--resume-on-limit",
        action="store_true",
        help="wait out a provider usage/rate limit and resume instead of stopping (supply loop)",
    )
    parser.add_argument(
        "--limit-backoff-seconds",
        type=_positive_float,
        default=30.0,
        help="initial back-off when the provider names no reset (default 30)",
    )
    parser.add_argument(
        "--limit-max-wait-seconds",
        type=_positive_float,
        default=3600.0,
        help="cap on a single usage-limit wait before re-polling (default 3600)",
    )


def _add_improve_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--headless",
        action="store_true",
        help="accepted for migration compatibility; no agent is launched",
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

    def cmd_ui(args, console):
        serve_ui(Path.cwd(), args.port)
        return 0

    handler = {
        "init": cmd_init,
        "run": cmd_run,
        "improve": cmd_improve,
        "verify": cmd_verify,
        "doctor": cmd_doctor,
        "revert": cmd_revert,
        "hook": cmd_hook,
        "install-hook": cmd_install_hook,
        "propose": cmd_propose,
        "next": cmd_next,
        "status": cmd_status,
        "swarm": cmd_swarm,
        "daemon": cmd_daemon,
        "migrate": cmd_migrate,
        "ui": cmd_ui,
    }[args.command]
    try:
        return handler(args, console)
    except ConfigError as exc:
        console.print(f"[red]config error:[/red] {exc}")
        return 2
    except KeyboardInterrupt:
        # Ctrl-C during a run should exit cleanly, not dump a traceback. (The
        # improve loop catches its own to roll back; this covers every command.)
        console.print("\n[yellow]interrupted[/yellow]")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
