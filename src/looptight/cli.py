from __future__ import annotations

import argparse
import sys

from rich.console import Console

from . import __version__
from .commands import (
    cmd_doctor,
    cmd_hook,
    cmd_improve,
    cmd_init,
    cmd_install_hook,
    cmd_lessons,
    cmd_propose,
    cmd_revert,
    cmd_run,
    cmd_verify,
)
from .config import ConfigError
from .detect import KNOWN_AGENTS

_COMMANDS = {
    "init",
    "run",
    "improve",
    "verify",
    "lessons",
    "doctor",
    "revert",
    "hook",
    "install-hook",
    "propose",
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

    p_improve = sub.add_parser(
        "improve", help="continuously discover and implement verified repository improvements"
    )
    _add_improve_flags(p_improve)

    p_verify = sub.add_parser("verify", help="run the verify command once and report")
    p_verify.add_argument("--verify", help="override the verify command")

    p_lessons = sub.add_parser("lessons", help="show or prune the lessons looptight has learned")
    p_lessons.add_argument("--agent", choices=KNOWN_AGENTS, help="which agent's memory file to read")
    p_lessons.add_argument("--clear", action="store_true", help="remove all lessons")
    p_lessons.add_argument("--prune", metavar="TEXT", help="remove lessons whose text contains TEXT")

    sub.add_parser("doctor", help="show the detected agent, verify command, and adapter status")

    p_revert = sub.add_parser("revert", help="undo the agent's uncommitted edits (restore to HEAD)")
    p_revert.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    p_propose = sub.add_parser(
        "propose", help="scan the repo for concrete signals and rank candidate tasks (no agent, no tokens)"
    )
    p_propose.add_argument("--json", action="store_true", help="emit the ranked candidates as JSON")
    p_propose.add_argument(
        "--limit", type=_non_negative_int, default=10, help="max candidates to show (default 10)"
    )

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
    parser.add_argument("--max-iterations", type=_positive_int, help="hard iteration cap")
    parser.add_argument(
        "--patience",
        type=int,
        help="stop early after N iterations with no measurable progress (0 = off)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        help="USD spend threshold; raise it above the safe default. Checked after each "
        "iteration, so a single agent call can overshoot it.",
    )
    parser.add_argument("--no-reflect", action="store_true", help="do not write lessons on failure")
    parser.add_argument(
        "--native",
        action="store_true",
        help="drive the agent's own loop where it has one (e.g. Claude /goal); verify still gates",
    )


def _add_improve_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", choices=KNOWN_AGENTS, help="agent to use (auto-detected if omitted)")
    parser.add_argument("--verify", help="override the per-task verify command")
    parser.add_argument("--max-iterations", type=_positive_int, help="per-task hard iteration cap")
    parser.add_argument("--patience", type=int, help="per-task no-progress patience (0 = off)")
    parser.add_argument(
        "--budget",
        type=float,
        help="optional cumulative session spend threshold; default uses provider limits",
    )
    parser.add_argument("--no-reflect", action="store_true", help="do not write lessons on failure")
    parser.add_argument("--native", action="store_true", help="use the agent's native loop where available")
    parser.add_argument("--push", action="store_true", help="push each verified autonomous commit")


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
        "improve": cmd_improve,
        "verify": cmd_verify,
        "lessons": cmd_lessons,
        "doctor": cmd_doctor,
        "revert": cmd_revert,
        "hook": cmd_hook,
        "install-hook": cmd_install_hook,
        "propose": cmd_propose,
    }[args.command]
    try:
        return handler(args, console)
    except ConfigError as exc:
        console.print(f"[red]config error:[/red] {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
