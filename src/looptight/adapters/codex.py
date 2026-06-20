"""Codex CLI adapter — supplies the loop via ``codex exec``.

Codex's headless mode is ``codex exec <prompt>``: it runs one task
autonomously and prints the final agent message to stdout. looptight wraps that
in its run → verify → continue loop, so ``verify`` stays the deterministic
oracle. Codex's ``/goal`` is *not* a native loop we can drive: it's an
interactive, self-graded objective + token-budget tracker (no verify command,
TUI-only slash command), so ``supports_native_loop`` stays False. See
``docs/STATUS.md``.

The run is bounded by the iteration cap. Codex reads ``AGENTS.md``.

NOTE: flags are kept minimal and may need tuning for your Codex version and
approval/sandbox settings; see ``binary``/``exec_args`` below.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from subprocess import CompletedProcess

from ..types import IterationResult
from .base import Adapter, run_command


class CodexAdapter(Adapter):
    name = "codex"
    memory_filename = "AGENTS.md"
    supports_native_loop = False

    binary = "codex"
    exec_args: tuple[str, ...] = ("exec",)

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _exec(self, prompt: str, workdir: Path) -> CompletedProcess[str]:
        cmd = [self.binary, *self.exec_args, prompt]
        return run_command(cmd, workdir)

    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        proc = self._exec(_build_prompt(goal, context), workdir)
        if proc.returncode != 0:
            return IterationResult(
                transcript=proc.stderr.strip() or "codex exited non-zero",
                ok=False,
                error=f"codex exited {proc.returncode}",
            )
        return IterationResult(transcript=proc.stdout.strip(), ok=True)

def _build_prompt(goal: str, context: str) -> str:
    parts = [
        f"Goal: {goal}",
        "Make concrete progress by editing files in this repo. A separate "
        "verification command decides success; just make the code correct.",
    ]
    if context.strip():
        parts += ["", "Context from the previous attempt:", context.strip()]
    return "\n".join(parts)
