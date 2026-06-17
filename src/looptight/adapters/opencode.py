"""opencode adapter — supplies the loop via ``opencode run``.

opencode's headless mode is ``opencode run <prompt>``, which executes one
non-interactive task and prints the result. It has no confirmed eval-gated goal
primitive, so looptight supplies the loop, exactly as for the supply path of the
others — keeping ``verify`` the ground-truth oracle.

opencode doesn't report a USD cost on stdout, so cost shows as $0.00 and the run
is bounded by the iteration cap (D1). opencode reads ``AGENTS.md``, where lessons
land.

NOTE: flags are kept minimal and may need tuning for your opencode version (e.g.
``-f json`` / ``-q`` / ``--model``); see ``binary``/``run_args`` below.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..types import IterationResult
from .base import Adapter


class OpencodeAdapter(Adapter):
    name = "opencode"
    memory_filename = "AGENTS.md"
    supports_native_loop = False

    binary = "opencode"
    run_args: tuple[str, ...] = ("run",)

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, prompt: str, workdir: Path) -> subprocess.CompletedProcess[str]:
        cmd = [self.binary, *self.run_args, prompt]
        return subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, check=False)

    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        proc = self._run(_build_prompt(goal, context), workdir)
        if proc.returncode != 0:
            return IterationResult(
                transcript=proc.stderr.strip() or "opencode exited non-zero",
                ok=False,
                error=f"opencode exited {proc.returncode}",
            )
        return IterationResult(transcript=proc.stdout.strip(), cost_usd=0.0, ok=True)

    def reflect(self, prompt: str, workdir: Path) -> str | None:
        proc = self._run("Do not modify any files. " + prompt, workdir)
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
