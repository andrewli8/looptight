"""opencode adapter — supplies the loop via ``opencode run``.

opencode's headless mode is ``opencode run <prompt>``, which executes one
non-interactive task and prints the result. It has no confirmed eval-gated goal
primitive, so looptight supplies the loop, exactly as for the supply path of the
others — keeping ``verify`` the ground-truth oracle.

The run is bounded by the iteration cap. opencode reads ``AGENTS.md``.

NOTE: flags are kept minimal and may need tuning for your opencode version (e.g.
``-f json`` / ``-q`` / ``--model``); see ``binary``/``run_args`` below.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from subprocess import CompletedProcess

from ..types import IterationResult
from .base import Adapter, failure_iteration, run_command


class OpencodeAdapter(Adapter):
    name = "opencode"
    memory_filename = "AGENTS.md"
    supports_native_loop = False

    binary = "opencode"
    run_args: tuple[str, ...] = ("run",)

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _run(self, prompt: str, workdir: Path) -> CompletedProcess[str]:
        cmd = [self.binary, *self.run_args, prompt]
        return run_command(cmd, workdir, timeout_s=self.worker_timeout_s)

    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        proc = self._run(_build_prompt(goal, context), workdir)
        if proc.returncode != 0:
            return failure_iteration(proc, self.name)
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
