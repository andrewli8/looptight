"""Claude Code Stop-hook integration: let Claude Code itself be the loop.

Registered as a Stop hook, ``looptight hook`` runs after every turn. It runs
``verify``; if the check fails it tells Claude to keep going (feeding the
failures back), up to the iteration cap. There is no goal string and no second
agent: the goal is whatever you already asked Claude to do. This is the supply
loop again, with the host Claude Code session as the agent instead of a spawned
``claude -p``.

The hook stays dormant unless two things hold: it is registered in Claude Code's
``settings.json`` (via ``looptight install-hook``), and the working directory has
a ``verify`` command configured — no verify, no loop. Loop state (how many
continuations we've forced this session) lives in a temp file keyed by Claude's
session id, never in the working tree, so it can't dirty ``verify``.

``decide`` is the pure core and carries the policy; ``run_hook`` is the thin I/O
shell that reads the event, loads state, and renders the response.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from .config import Config, ConfigError, find_config, load_config
from .types import VerifyResult
from .verify import run_verify

VerifyFn = Callable[[str, Path], VerifyResult]
WorkFn = Callable[[Path], bool]
DriftFn = Callable[[Path], "str | None"]


def _changed_files(cwd: Path) -> list[str]:
    """Repo-relative files with uncommitted changes (staged + unstaged) vs HEAD.

    Empty on any git error, so an adverse repo state never produces a false drift signal.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=cwd,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _off_task(evidence_paths: list[str], changed_files: list[str]) -> bool:
    """True only when there ARE changes and NONE relate to the claimed task's evidence.

    Conservative on purpose: a change is "on task" if it is the evidence file itself or shares the
    evidence file's stem (so the source file *and* its sibling test — ``foo.py`` and
    ``tests/test_foo.py`` — both count). Directory is intentionally NOT scope: in a flat layout
    every file shares a directory, which would make drift never fire. Drift fires only when the
    diff is wholly unrelated to every evidence anchor. An empty diff or empty evidence is never drift.
    """
    if not changed_files or not evidence_paths:
        return False
    for path in evidence_paths:
        stem = PurePosixPath(path).stem
        for changed in changed_files:
            if changed == path or (stem and stem in PurePosixPath(changed).name):
                return False  # at least one change relates to the claimed task
    return True


def drift_reason(goal: str, evidence_paths: list[str], changed: list[str]) -> str:
    """What we feed back when the diff has wholly left the claimed task's evidence scope."""
    return (
        f"looptight: your changes ({', '.join(changed[:5])}) don't touch the evidence of your "
        f"claimed task ({', '.join(evidence_paths[:3])}). Refocus on that task — {goal} — or "
        "claim a different one with `looptight next` before stopping."
    )


def _drift_directive(cwd: Path) -> str | None:
    """A refocus message when this worktree's session has drifted off its claimed task, else None.

    Reads the owner's live lease (the claimed task) and the uncommitted diff; any coordinator or
    git error is swallowed so the hook never traps the session on an adverse state.
    """
    try:
        from .claims import owner_id
        from .coordinator import Coordinator
        from .grounding import evidence_refs, strip_position_suffix

        coordinator = Coordinator.open(cwd)
        if coordinator is None:
            return None
        try:
            lease = coordinator.active_lease_for_owner(owner_id(cwd))
        finally:
            coordinator.close()
        if lease is None:
            return None
        evidence_paths = [strip_position_suffix(ref) for ref in evidence_refs(str(lease.payload.get("evidence") or ""))]
        if not _off_task(evidence_paths, _changed_files(cwd)):
            return None
        goal = str(lease.payload.get("goal") or lease.payload.get("id") or "your claimed task")
        return drift_reason(goal, evidence_paths, _changed_files(cwd))
    except Exception:
        return None


def _has_grounded_work(cwd: Path) -> bool:
    """True when `propose` finds at least one grounded candidate (read-only; claims nothing).

    Any discovery/coordinator error is swallowed and read as 'no work', so an adverse repo
    state never traps the session in a forced loop.
    """
    try:
        from .propose import propose

        return bool(propose(cwd, limit=0))
    except Exception:
        return False


@dataclass(frozen=True)
class HookDecision:
    """What we tell Claude Code after a turn: keep going, or let it stop."""

    block: bool
    reason: str = ""

    def to_stdout(self) -> str | None:
        """The JSON line to print, or None to allow the stop silently."""
        if not self.block:
            return None
        return json.dumps({"decision": "block", "reason": self.reason})


def continuation_reason(verify: VerifyResult) -> str:
    """What we feed back to Claude when verify still fails."""
    return (
        f"looptight: verification still fails ({verify.short()}). Keep going and "
        "fix the specific failures below; do not stop until the verify command "
        f"passes.\n\n{verify.context_output(3000)}"
    )


def backlog_reason() -> str:
    """What we feed back when the change is green but grounded tasks still remain."""
    return (
        "looptight: verification passed and grounded tasks remain. Run `looptight next` "
        "to claim the top one and implement it, then verify and commit. Stop only when "
        "`next` reports NO_WORK — do not fabricate work to keep busy."
    )


def decide(
    verify: VerifyResult,
    prior_blocks: int,
    max_iterations: int,
    *,
    work_remains: bool = False,
    continue_on_work: bool = False,
) -> tuple[HookDecision, int]:
    """Pure policy core.

    Given the latest verify result and how many continuations we've already
    forced this user-turn, decide whether to force another, and return the new
    count. Resets to 0 when verify passes with nothing left to do, or the cap is
    reached, so a later user request starts with a fresh budget of continuations.

    Two reasons to keep going: the current change is not yet green (``verify``
    fails), or — only when ``continue_on_work`` is set — the change is green but
    claimable grounded work remains (``work_remains``). When verify passes and no
    grounded work remains, the stop is allowed: an honest stop, not a forced one.
    """
    if not verify.passed:
        if prior_blocks >= max_iterations:
            return HookDecision(block=False), 0
        return HookDecision(block=True, reason=continuation_reason(verify)), prior_blocks + 1
    # The current change is green.
    if continue_on_work and work_remains and prior_blocks < max_iterations:
        return HookDecision(block=True, reason=backlog_reason()), prior_blocks + 1
    return HookDecision(block=False), 0


def _state_path(session_id: str, cwd: Path) -> Path:
    key = hashlib.sha256(f"{session_id}:{cwd}".encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "looptight-hooks" / f"{key}.count"


def read_count(path: Path) -> int:
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 0


def write_count(path: Path, count: int) -> None:
    if count <= 0:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(count))


def _config_for(cwd: Path) -> Config:
    found = find_config(cwd)
    if not found:
        return Config()
    try:
        return load_config(found)
    except ConfigError:
        # A broken config must never trap or crash the hook; treat it as an
        # un-armed repo (dormant default) and let the stop through.
        return Config()


def run_hook(
    stdin_text: str,
    *,
    verify_fn: VerifyFn = run_verify,
    work_fn: WorkFn = _has_grounded_work,
    drift_fn: DriftFn = _drift_directive,
) -> tuple[str | None, int]:
    """Process one Stop-hook event.

    Returns ``(stdout_or_None, exit_code)``. Anything that isn't a clean "block"
    decision allows the stop, so a missing config, a malformed event, or an
    un-armed repo never traps Claude in a loop.
    """
    try:
        event = json.loads(stdin_text or "{}")
    except ValueError:
        return None, 0
    if not isinstance(event, dict):
        return None, 0

    cwd_value = event.get("cwd")
    if cwd_value is not None and not isinstance(cwd_value, str):
        return None, 0
    cwd = Path(cwd_value or Path.cwd())
    session_id = str(event.get("session_id") or "default")

    config = _config_for(cwd)
    if not config.verify:
        return None, 0

    state = _state_path(session_id, cwd)
    # A fresh, user-initiated stop resets the continuation budget; a stop that is
    # itself the result of our previous block carries the running count forward.
    prior = read_count(state) if event.get("stop_hook_active") else 0

    verify = verify_fn(config.verify, cwd)
    # When opted in and the change is green, first check for drift (the session left its claimed
    # task's scope) — refocus takes priority over draining the backlog — then for remaining work.
    drift = drift_fn(cwd) if config.continue_through_backlog and verify.passed else None
    if drift and prior < config.max_iterations:
        decision, new_count = HookDecision(block=True, reason=drift), prior + 1
    else:
        work_remains = config.continue_through_backlog and verify.passed and work_fn(cwd)
        decision, new_count = decide(
            verify,
            prior,
            config.max_iterations,
            work_remains=work_remains,
            continue_on_work=config.continue_through_backlog,
        )
    try:
        write_count(state, new_count)
    except OSError:
        # Without durable state a failing verify could be blocked forever because
        # every invocation would restart at zero. Fail open instead.
        return None, 0
    return decision.to_stdout(), 0
