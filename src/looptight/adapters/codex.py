"""Codex CLI adapter — supplies the loop via ``codex exec``.

Codex's headless mode is ``codex exec <prompt>``: it runs one task
autonomously and prints the final agent message to stdout. looptight wraps that
in its run → verify → continue loop, so ``verify`` stays the deterministic
oracle (rather than depending on whether Codex's interactive ``/goal`` can be
driven headlessly — an unconfirmed capability we deliberately don't fake).

Codex doesn't report a USD cost on stdout, so cost shows as $0.00 and the run is
bounded by the iteration cap (D1). Codex reads ``AGENTS.md``, where lessons land.

NOTE: flags are kept minimal and may need tuning for your Codex version and
approval/sandbox settings; see ``binary``/``exec_args`` below.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..types import IterationResult
from .base import Adapter


class CodexAdapter(Adapter):
    name = "codex"
    memory_filename = "AGENTS.md"
    supports_native_loop = False

    binary = "codex"
    exec_args: tuple[str, ...] = ("exec",)

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _exec(self, prompt: str, workdir: Path) -> subprocess.CompletedProcess[str]:
        cmd = [self.binary, *self.exec_args, prompt]
        return subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, check=False)

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
        return IterationResult(transcript=proc.stdout.strip(), cost_usd=0.0, ok=True)

    def reflect(self, prompt: str, workdir: Path) -> str | None:
        proc = self._exec("Do not modify any files. " + prompt, workdir)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None


def _build_prompt(goal: str, context: str) -> str:
    parts = [
        f"Goal: {goal}",
        "Make concrete progress by editing files in this repo. A separate "
        "verification command decides success; just make the code correct.",
    ]
    if context.strip():
        parts += ["", "Context from the previous attempt:", context.strip()]
    return "\n".join(parts)
