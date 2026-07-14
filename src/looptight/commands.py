"""Human-facing CLI handlers and stable exports for protocol handlers."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .adapters import available_adapter_names, get_adapter
from .checkpoint import is_git_primary_worktree, is_git_repo
from .claims import claim_dir, has_live_claim
from .config import CONFIG_NAME, DEFAULT_VERIFY, Config, find_config, load_config, write_config
from .console import Console
from .coordinator import coordination_scope
from .daemon import run_daemon
from .detect import KNOWN_AGENTS, detect_agent, detect_verify
from .fsutil import atomic_write_text
from .integration import install_goal_instructions, install_session_instructions
from .loop import run_loop
from .protocol_commands import (
    cmd_goal,
    cmd_migrate,
    cmd_next,
    cmd_propose,
    cmd_status,
    cmd_verify,
    humanized_checks,
    policy_line,
)
from .summary import render_rich
from .swarm import MAX_WORKERS, cmd_swarm
from .types import StopReason
from .ui import _with_session_task, read_state, statusline

__all__ = [
    "cmd_daemon",
    "cmd_doctor",
    "cmd_goal",
    "cmd_hook",
    "cmd_improve",
    "cmd_init",
    "cmd_install_hook",
    "cmd_install_skill",
    "cmd_migrate",
    "cmd_next",
    "cmd_propose",
    "cmd_revert",
    "cmd_run",
    "cmd_status",
    "cmd_statusline",
    "cmd_swarm",
    "cmd_verify",
]


def _is_python_verify(command: str) -> bool:
    """True when the verify command runs Python tests, which create __pycache__/."""
    lowered = command.lower()
    return "pytest" in lowered or "py.test" in lowered or "python -m" in lowered


def _ensure_pycache_ignored(workdir: Path, console: Console) -> None:
    """Ensure .gitignore contains __pycache__/, creating or appending as needed.

    A Python verify command leaves untracked __pycache__/ behind; without a .gitignore
    entry the next `looptight next` refuses the dirty worktree. When .gitignore already
    exists and already lists __pycache__/, it is left untouched. When it exists but
    lacks the entry, the line is appended — never rewriting the user's existing rules.
    """
    gitignore = workdir / ".gitignore"
    if gitignore.exists():
        try:
            content = gitignore.read_text(encoding="utf-8")
        except OSError:
            return
        if any("__pycache__" in line for line in content.splitlines()):
            return
        new_content = content + ("" if content.endswith("\n") else "\n") + "__pycache__/\n"
    else:
        new_content = "__pycache__/\n"
    atomic_write_text(gitignore, new_content)
    console.print(
        "[green]wrote[/green] .gitignore (__pycache__/) so test runs don't dirty the "
        "worktree and stall [bold]looptight next[/bold]."
    )


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
            if args.verify:
                console.print(f"Using [cyan]{verify}[/cyan] from --verify. Edit {path.name} if that's wrong.")
            else:
                console.print(f"Detected: [cyan]{verify}[/cyan]. Edit {path.name} if that's wrong.")
            from .protocol_commands import _verifier_quality

            quality = _verifier_quality(verify)
            if quality["classification"] in ("lint-only", "none", "custom/unknown"):
                console.print(f"[yellow]note:[/yellow] {quality['risk']}")
        else:
            console.print(
                f"[yellow]No test command detected.[/yellow] Wrote a default "
                f"[cyan]{DEFAULT_VERIFY}[/cyan] — replace it in {path.name} with your "
                "project's test command."
            )
        # The effective verify is pytest even when none is detected (config falls back to
        # DEFAULT_VERIFY), so guard the Python happy path against the __pycache__ stall.
        if _is_python_verify(verify or DEFAULT_VERIFY):
            _ensure_pycache_ignored(workdir, console)
        if agent:
            source = "from --agent" if args.agent else "auto-detected"
            console.print(f"Agent: [cyan]{agent}[/cyan] ({source}).")
        else:
            console.print("[yellow]No coding agent found on PATH (claude / codex / opencode).[/yellow]")
        console.print()
        console.print(
            f"Commit [cyan]{path.name}[/cyan] before [bold]looptight next[/bold] — "
            "it requires a clean worktree."
        )

    if args.integrate:
        changed = install_session_instructions(workdir)
        changed += install_goal_instructions(workdir)
        state = "installed" if changed else "already installed"
        console.print(f"[green]{state}[/green] session and goal loops for Codex, Claude Code, and OpenCode")
    elif not config_exists:
        console.print()
        console.print("For the native current-session loop: [bold]looptight init --integrate[/bold]")
    if detect_agent() == "claude":
        console.print(
            "To let Claude Code discover looptight in any session: "
            "[bold]looptight install-skill[/bold]"
        )
    if not is_git_repo(workdir):
        console.print(
            "[yellow]Note:[/yellow] this directory is not a git repository. "
            "Run [bold]git init[/bold] first — [bold]looptight next[/bold] requires a git repository."
        )
    return 0


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    as_json = getattr(args, "json", False)

    def _guard_fail(human: str, machine: str) -> int:
        # A guard failure must honor whichever contract the caller asked for: a
        # JSON error object under --json, Rich markup otherwise.
        if as_json:
            import json

            print(json.dumps({"command": "run", "schema_version": 1, "error": machine}))
        else:
            console.print(human)
        return 2

    if not args.headless:
        return _guard_fail(
            "[red]run launches an agent child process.[/red] Pass --headless explicitly, "
            "or use `looptight init --integrate` for the current-session loop.",
            "run launches an agent child process; pass --headless explicitly",
        )
    workdir = Path.cwd()
    config = load_config().merged(
        agent=args.agent,
        model=args.model,
        verify=args.verify,
        max_iterations=args.max_iterations,
        patience=args.patience,
        native=True if args.native else None,
    )
    if is_git_primary_worktree(workdir) and not config.direct_main:
        return _guard_fail(
            "[red]run --headless refuses a Git primary worktree by default.[/red] "
            "Use an isolated worktree, or set `direct_main = true` explicitly.",
            "run --headless refuses a Git primary worktree; use an isolated worktree "
            "or set direct_main = true",
        )

    agent_name = config.agent or detect_agent()
    if not agent_name:
        return _guard_fail(
            "[red]No coding agent found on PATH.[/red] Install claude, codex, or opencode.",
            "no coding agent found on PATH; install claude, codex, or opencode",
        )
    adapter = get_adapter(agent_name)

    if not config.verify:
        config = config.merged(verify=detect_verify(workdir))
    if not config.verify:
        return _guard_fail(
            "[red]No verify command.[/red] No verify, no loop — set one:\n"
            '  looptight init   or   looptight run --headless "..." --verify "pytest -q"',
            "no verify command; run looptight init or pass --verify",
        )

    use_native = config.native and adapter.supports_native_loop
    if config.native and not adapter.supports_native_loop:
        console.print(f"[yellow]{agent_name} has no native loop; supplying the loop instead.[/yellow]")

    if not as_json:
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
            args.goal,
            adapter,
            config,
            workdir,
            native=use_native,
            on_iteration=None if as_json else on_iteration,
            resume_on_limit=args.resume_on_limit,
            limit_backoff_seconds=args.limit_backoff_seconds,
            limit_max_wait_seconds=args.limit_max_wait_seconds,
        )
    except NotImplementedError as exc:
        if as_json:
            import json
            print(json.dumps({"command": "run", "schema_version": 1, "error": str(exc)}))
            return 3
        console.print(f"[yellow]{exc}[/yellow]")
        return 3

    if as_json:
        import json
        print(json.dumps(result.as_dict(), sort_keys=True))
    else:
        # The banner and per-iteration lines were already streamed live above, so the summary
        # prints only the conclusion (done line, escalation, diffstat) — not a duplicate of them.
        render_rich(result, console, include_progress=False)
    return 0 if result.stop_reason is StopReason.SUCCESS else 1


def cmd_daemon(args: argparse.Namespace, console: Console) -> int:
    """Run looptight as a persistent supervisor: a continuous swarm that restarts
    forever, looping promptly after merged progress, polling after a back-off when
    idle, and backing off (capped) on faults. This is the piece that turns the
    bounded continuous swarm into true 24/7 operation; it needs a host that stays
    up and an authenticated agent. Stops gracefully on Ctrl-C / SIGTERM."""
    if not args.headless:
        console.print("[red]daemon launches agent child processes.[/red] Pass --headless explicitly.")
        return 2
    if args.workers > MAX_WORKERS:
        console.print(f"[red]workers must be between 1 and {MAX_WORKERS}[/red]")
        return 2
    config = load_config().merged(
        agent=args.agent,
        model=args.model,
        verify=args.verify,
        max_iterations=args.max_iterations,
        idea_generation=False if args.no_ideas else None,
    )
    agent = config.agent or detect_agent()
    if not agent:
        console.print("[red]No coding agent found on PATH.[/red] Install claude, codex, or opencode.")
        return 2
    if not config.verify:
        config = config.merged(verify=detect_verify(Path.cwd()))
    if not config.verify:
        console.print("[red]No verify command.[/red] Configure one before starting the daemon.")
        return 2

    stop = {"flag": False}

    def request_stop(signum, frame) -> None:
        if not stop["flag"]:
            console.print("\n[yellow]shutdown requested — stopping after the current cycle…[/yellow]")
        stop["flag"] = True

    def interruptible_sleep(seconds: float) -> None:
        # Sleep in short steps so a stop signal is honored within ~1s instead of
        # waiting out a full idle interval (systemd would otherwise SIGKILL us).
        deadline = time.monotonic() + seconds
        while not stop["flag"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 1.0))

    def on_cycle(cycle) -> None:
        style = {"progress": "green", "idle": "cyan", "fault": "red"}.get(cycle.outcome, "white")
        if cycle.outcome == "fault" and cycle.error:
            detail = f" — {cycle.error}"
        elif cycle.merged:
            detail = f" ({cycle.merged} merged)"
        else:
            detail = ""
        nxt = "next now" if cycle.delay == 0 else f"next in {int(cycle.delay)}s"
        console.print(f"cycle {cycle.index} → [{style}]{cycle.outcome}[/{style}]{detail}; {nxt}")

    model = f" ({config.model})" if config.model else ""
    console.print(
        f"[bold]looptight daemon[/bold] · agent: [cyan]{agent}[/cyan]{model} · "
        f"workers: [cyan]{args.workers}[/cyan] · verify: [cyan]{config.verify}[/cyan] · "
        f"{'pushing to main' if args.push else 'local commits only'}"
    )
    console.print("Ctrl-C or SIGTERM to stop after the current cycle.")
    console.print()

    def fault_hook(payload: dict) -> None:
        # Operator notification on a fault backoff. Best-effort: a failing hook
        # must never crash the daemon (run_daemon also guards, this guards exec).
        import json

        try:
            subprocess.run(
                args.on_fault, shell=True, input=json.dumps(payload),
                text=True, timeout=30, check=False,
            )
        except Exception:
            pass

    restore: list[tuple[int, object]] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            restore.append((sig, signal.signal(sig, request_stop)))
        except (ValueError, OSError):  # not the main thread / signal unsupported
            pass
    try:
        report = run_daemon(
            Path.cwd(),
            agent=agent,
            config=config,
            workers=args.workers,
            worker_timeout=args.worker_timeout,
            push=args.push,
            resume_on_limit=not args.no_resume_on_limit,
            max_idle_rounds=args.max_idle_rounds,
            idle_sleep_seconds=args.idle_sleep,
            fault_backoff_seconds=args.fault_backoff,
            fault_max_backoff_seconds=args.fault_max_backoff,
            max_cycles=args.max_cycles,
            sleep=interruptible_sleep,
            should_stop=lambda: stop["flag"],
            on_cycle=on_cycle,
            on_fault=fault_hook if args.on_fault else None,
        )
    finally:
        for sig, prev in restore:
            try:
                signal.signal(sig, prev)
            except (ValueError, OSError):
                pass

    console.print()
    console.print(
        f"[bold]daemon stopped[/bold] · cycles: {report.cycles} "
        f"(progress {report.progress}, idle {report.idle}, faults {report.faults})"
    )
    return 0


def cmd_improve(args: argparse.Namespace, console: Console) -> int:
    console.print(
        "[yellow]improve is deprecated and no longer launches agents.[/yellow] "
        "Use `looptight init --integrate`, then `next`, `verify`, and `status` "
        "inside the current agent session."
    )
    return 2


def cmd_doctor(args: argparse.Namespace, console: Console) -> int:
    import json as _json

    from .protocol_commands import _readiness

    workdir = Path.cwd()
    config = load_config()
    agent = config.agent or detect_agent()
    verify = config.verify or detect_verify(workdir)

    # Readiness drives a scriptable exit code: "unsafe" (no verify, or a dirty or
    # non-Git worktree) is non-zero so CI can gate on it; otherwise zero.
    try:
        git = subprocess.run(
            ["git", "status", "--porcelain"], cwd=workdir,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True, text=True, check=False,
        )
    except OSError:
        git = None
    workspace = (
        "not_git" if git is None or git.returncode != 0
        else ("dirty" if git.stdout.strip() else "clean")
    )
    readiness = _readiness(
        workdir=workdir, verify=verify, workspace=workspace,
        config_tasks=config.tasks, agent=agent,
        fallback_action="run `looptight next --json`",
    )
    unsafe = readiness["tier"] == "unsafe"

    if getattr(args, "json", False):
        print(_json.dumps(
            {"command": "doctor", "schema_version": 1, "readiness": readiness,
             "agent": agent, "verify": verify},
            sort_keys=True,
        ))
        return 1 if unsafe else 0

    config_path = find_config(workdir)
    console.print("[bold]looptight doctor[/bold]")
    console.print(
        f"  config: {config_path}" if config_path else "  config: none (using defaults)"
    )
    console.print(f"  agent (detected): {agent or '[red]none on PATH[/red]'}")
    console.print(f"  verify (detected): {verify or '[yellow]none[/yellow]'}")
    configured_policy = policy_line(config)
    if configured_policy:  # show the safety rails the user configured (else only in --json)
        console.print(f"  {configured_policy}")
    git_ready = is_git_repo(workdir)
    coordinator = _doctor_coordinator_state(workdir, git_ready)
    console.print(f"  git checkpoints: {'on' if git_ready else '[yellow]off (not a git repo)[/yellow]'}")
    console.print(f"  coordinator: {coordinator}")
    console.print(f"  coordination: {_coordination_line(workdir)}")
    # Setup readiness is about verify + agent + git; the coordinator is already the
    # claim store in any git repo, so it is never a setup requirement.
    setup_ready = bool(verify and agent and git_ready)
    console.print(f"  setup: {'ready' if setup_ready else 'not ready'}")
    # The readiness tier matches the exit code: `unsafe` exits non-zero, `partial`
    # and `ready` exit zero (looping is possible even if setup is not fully complete).
    console.print(f"  readiness: {readiness['tier']} (exit {1 if unsafe else 0})")
    # Explain the verdict inline so the diagnostic is self-contained — the same reasons
    # `status` shows, rather than making the operator run a second command to learn why.
    checks = readiness.get("checks")
    if isinstance(checks, dict) and checks:
        console.print("  readiness checks: " + humanized_checks(checks))
    console.print(
        f"  setup next: {_doctor_next_setup_command(verify, agent, git_ready)}"
    )
    # The coordinator is already the claim store; `migrate` only fences legacy file
    # claims, so it is only worth suggesting when live legacy claims actually exist.
    claims = claim_dir(workdir) if git_ready else None
    if claims is not None and has_live_claim(claims):
        console.print("  hint: `looptight migrate` fences live legacy file claims into the coordinator")
    console.print("  adapters:")
    for name in available_adapter_names():
        adapter = get_adapter(name)
        status = "available" if adapter.is_available() else "not installed"
        loop = "supply + native loop (--native)" if adapter.supports_native_loop else "supply"
        console.print(f"    - {name}: {loop}, {status}")
    # Point the operator at the fix when a prerequisite is missing; stay silent
    # (lines unchanged) when both are present.
    if not verify:
        console.print(
            "  [yellow]hint:[/yellow] no verify command — run `looptight init` to detect one."
        )
    if not agent:
        supported = ", ".join(KNOWN_AGENTS)
        console.print(
            f"  [yellow]hint:[/yellow] no agent on PATH — install one of: {supported}."
        )
    return 1 if unsafe else 0


# Both git states use the SQLite coordinator as the claim store; the marker only
# records whether legacy file claims have been fenced, so neither human label
# should imply file claims are the coordination mechanism.
_COORDINATION_LABELS = {
    "coordinator": "local-only (SQLite coordinator)",
    "file-claims": "local-only (SQLite coordinator)",
    "none": "not a git repo",
}


def _coordination_line(workdir: Path) -> str:
    """One-line coordination scope for `doctor`, naming the single-machine boundary."""
    scope = coordination_scope(workdir)
    label = _COORDINATION_LABELS[scope]
    if scope == "none":
        return label
    return f"{label}; cross-machine sharing is unsupported"


def _doctor_coordinator_state(workdir: Path, git_ready: bool) -> str:
    # `next` leases through the coordinator DB in any git repo, so the coordinator
    # is the active claim store whenever git checkpoints are on. The migrate marker
    # only fences legacy file claims and is surfaced separately.
    return "active" if git_ready else "not a git repo"


def _doctor_next_setup_command(
    verify: str | None, agent: str | None, git_ready: bool
) -> str:
    if not verify:
        return "run `looptight init --integrate`"
    if not git_ready:
        return "run inside a Git repository"
    if not agent:
        supported = ", ".join(KNOWN_AGENTS)
        return f"install a supported agent CLI ({supported})"
    # The coordinator is optional (cross-session only), surfaced as a hint, so it
    # is not part of the required setup path.
    return "run `looptight next --json`"


def cmd_revert(args: argparse.Namespace, console: Console) -> int:
    workdir = Path.cwd()
    if not is_git_repo(workdir):
        console.print("[yellow]Not a git repo — nothing to revert.[/yellow]")
        return 1
    import subprocess

    # Check for tracked changes BEFORE the confirmation prompt: a clean tree has
    # nothing to discard, so neither the prompt nor a checkout is warranted.
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(workdir), env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True, text=True, check=False,
        )
    except OSError:
        status = None
    has_tracked_changes = (
        status is None or status.returncode != 0 or bool((status.stdout or "").strip())
    )

    if has_tracked_changes and not args.yes:
        console.print("This discards uncommitted changes (restores tracked files to HEAD).")
        console.print("Re-run with [bold]--yes[/bold] to confirm.")
        return 0

    if has_tracked_changes:
        try:
            result = subprocess.run(
                ["git", "checkout", "HEAD", "--", "."], cwd=str(workdir),
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, check=False,
            )
        except OSError as exc:
            console.print(f"[red]error:[/red] could not run git checkout: {exc}")
            return 1
        if result.returncode != 0:
            console.print("[red]error:[/red] git checkout failed; restore not confirmed. Inspect the working tree.")
            return 1
        console.print("[green]reverted[/green] tracked files to HEAD.")
    else:
        console.print("working tree already clean — nothing to revert.")
    # revert is tracked-only by design; tell the user about any untracked files
    # the agent created so the leftover state isn't a surprise. This is purely
    # informational — never let it crash a revert that already succeeded.
    try:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(workdir),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
        leftovers = untracked.stdout.splitlines() if untracked.returncode == 0 else []
    except OSError:
        leftovers = []
    if leftovers:
        console.print(
            f"[yellow]{len(leftovers)} untracked file{'s' if len(leftovers) != 1 else ''} left in place[/yellow] — revert only "
            "touches tracked files; remove them with `git clean -fd` if unwanted."
        )
    return 0


def cmd_statusline(args: argparse.Namespace, console: Console) -> int:
    """Claude Code status-line entry point. Reads the status-line JSON on stdin and
    prints one concise line of swarm state to stdout. Must never error or hang."""
    import json

    raw = ""
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    repo = Path.cwd()
    try:
        data = json.loads(raw) if raw.strip() else {}
        candidate = None
        if isinstance(data, dict):
            workspace = data.get("workspace")
            if isinstance(workspace, dict):
                candidate = workspace.get("current_dir") or workspace.get("project_dir")
            candidate = candidate or data.get("cwd")
        if isinstance(candidate, str) and candidate:
            repo = Path(candidate)
    except (ValueError, TypeError):
        pass
    try:
        # Overlay the session's claimed task so the bar shows current work on the default loop,
        # not just swarm workers.
        print(statusline(_with_session_task(read_state(repo), repo)))
    except Exception:  # a status line must never break the host editor
        print("looptight: idle")
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


def cmd_install_skill(args: argparse.Namespace, console: Console) -> int:
    from .skill import SKILL_MD, install_skill, skill_path

    path = skill_path()
    already_current = False
    if path.is_file():
        try:
            already_current = path.read_text(encoding="utf-8") == SKILL_MD
        except (OSError, ValueError):
            # ValueError covers a non-UTF-8 file's UnicodeDecodeError: an unreadable
            # existing skill is simply treated as not-current and rewritten.
            already_current = False
    install_skill()  # always (re)write so an upgraded package refreshes the file
    if already_current:
        console.print(f"the looptight skill is already up to date at {path}")
    else:
        console.print(f"[green]installed[/green] the looptight skill at {path}")
    console.print("Claude Code will now discover looptight in any session.")
    return 0


def cmd_install_hook(args: argparse.Namespace, console: Console) -> int:
    from .settings import install, project_settings_path, uninstall, user_settings_path

    path = project_settings_path(Path.cwd()) if args.project else user_settings_path()
    try:
        if args.uninstall:
            removed = uninstall(path)
            console.print(f"removed {removed} looptight hook{'s' if removed != 1 else ''} from {path}")
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
    if args.project:
        # A project install lives in this repo's .claude/settings.json, so it is repo-scoped.
        console.print("The hook fires in [cyan]this repo[/cyan]'s Claude Code sessions once it has a [cyan]verify[/cyan] command.")
        console.print("Run [cyan]looptight init[/cyan] here if you have not set one up.")
    else:
        console.print("The hook fires in any repo that has a [cyan]verify[/cyan] command configured.")
        console.print("Run [cyan]looptight init[/cyan] in a project to set one up.")
    return 0
