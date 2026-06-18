"""Claude Code Stop-hook integration: let Claude Code itself be the loop.

Registered as a Stop hook, ``looptight hook`` runs after every turn. It runs
``verify``; if the check fails it tells Claude to keep going (feeding the
failures back), up to the iteration cap. There is no goal string and no second
agent: the goal is whatever you already asked Claude to do. This is the supply
loop again, with the host Claude Code session as the agent instead of a spawned
``claude -p``.

The hook stays dormant unless the repo opts in: the working directory must hold
a ``.looptight.toml`` with ``hook = true``. Loop state (how many continuations
we've forced this session) lives in a temp file keyed by Claude's session id,
never in the working tree, so it can't dirty ``verify``.

``decide`` is the pure core and carries the policy; ``run_hook`` is the thin I/O
shell that reads the event, loads state, and renders the response.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import Config, find_config, load_config
from .types import VerifyResult
from .verify import run_verify

VerifyFn = Callable[[str, Path], VerifyResult]


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
        f"passes.\n\n{verify.output[-3000:]}"
    )


def decide(
    verify: VerifyResult, prior_blocks: int, max_iterations: int
) -> tuple[HookDecision, int]:
    """Pure policy core.

    Given the latest verify result and how many continuations we've already
    forced this user-turn, decide whether to force another, and return the new
    count. Resets to 0 when verify passes or the cap is reached, so a later
    user request starts with a fresh budget of continuations.
    """
    if verify.passed:
        return HookDecision(block=False), 0
    if prior_blocks >= max_iterations:
        return HookDecision(block=False), 0
    return HookDecision(block=True, reason=continuation_reason(verify)), prior_blocks + 1


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
    return load_config(found) if found else Config()


def run_hook(stdin_text: str, *, verify_fn: VerifyFn = run_verify) -> tuple[str | None, int]:
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

    cwd = Path(event.get("cwd") or Path.cwd())
    session_id = str(event.get("session_id") or "default")

    config = _config_for(cwd)
    if not config.hook or not config.verify:
        return None, 0

    state = _state_path(session_id, cwd)
    # A fresh, user-initiated stop resets the continuation budget; a stop that is
    # itself the result of our previous block carries the running count forward.
    prior = read_count(state) if event.get("stop_hook_active") else 0

    verify = verify_fn(config.verify, cwd)
    decision, new_count = decide(verify, prior, config.max_iterations)
    write_count(state, new_count)
    return decision.to_stdout(), 0
