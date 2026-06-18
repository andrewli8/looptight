"""Claude Code adapter.

Claude Code has both a headless one-shot mode (``claude -p``) and a native
eval-gated loop (``/goal``, shipped 2026), so this adapter does both:

- **supply** (default): each iteration runs ``claude -p <prompt> --output-format
  json`` and we read the agent's own ``total_cost_usd`` (D2/D3) rather than
  guessing.
- **delegate** (``--native``): drive ``claude -p "/goal …"`` and let Claude's own
  Haiku evaluator gate the condition. looptight still runs ``verify`` afterward
  as the contract.

Auth-neutral (A4): we invoke whatever ``claude`` is on PATH and let it use its
existing auth. Claude Code auto-loads ``CLAUDE.md``, which is where lessons land.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..types import IterationResult
from .base import Adapter

# A small, cheap model for the bookkeeping/reflection step (D3). The coding step
# uses whatever the agent defaults to; only reflection is pinned cheap.
CHEAP_MODEL = "haiku"


class ClaudeAdapter(Adapter):
    name = "claude"
    memory_filename = "CLAUDE.md"
    supports_native_loop = True
    reports_cost_usd = True

    binary = "claude"

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _invoke(self, prompt: str, workdir: Path, model: str | None) -> subprocess.CompletedProcess[str]:
        cmd = [self.binary, "-p", prompt, "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        return subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True, check=False)

    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        proc = self._invoke(_build_prompt(goal, context), workdir, model)
        if proc.returncode != 0:
            return IterationResult(
                transcript=proc.stderr.strip() or "claude exited non-zero",
                ok=False,
                error=f"claude exited {proc.returncode}",
            )
        transcript, cost = _parse_result(proc.stdout)
        return IterationResult(transcript=transcript, cost_usd=cost, ok=True)

    def drive_native_loop(
        self,
        goal: str,
        verify: str,
        max_iterations: int,
        budget_usd: float,
        workdir: Path,
    ) -> IterationResult:
        prompt = (
            f"/goal {goal}. Keep going until the command `{verify}` exits with "
            f"status 0. Stop after at most {max_iterations} attempts."
        )
        proc = self._invoke(prompt, workdir, None)
        transcript, cost = _parse_result(proc.stdout)
        if proc.returncode != 0 and not transcript:
            transcript = proc.stderr.strip() or "claude /goal exited non-zero"
        return IterationResult(transcript=transcript, cost_usd=cost, ok=proc.returncode == 0)

    def reflect(self, prompt: str, workdir: Path) -> str | None:
        proc = self._invoke(prompt, workdir, CHEAP_MODEL)
        if proc.returncode != 0:
            return None
        transcript, _ = _parse_result(proc.stdout)
        return transcript.strip() or None


def _build_prompt(goal: str, context: str) -> str:
    """Compose the continuation prompt for one supplied iteration."""
    parts = [
        f"Goal: {goal}",
        "",
        "Make concrete progress toward the goal by editing files in this repo.",
        "A separate verification command decides success — do not try to run or "
        "fake it; just make the code correct.",
    ]
    if context.strip():
        parts += ["", "Context from the previous attempt:", context.strip()]
    return "\n".join(parts)


def _parse_result(stdout: str) -> tuple[str, float]:
    """Pull (result text, cost_usd) out of Claude Code's JSON output."""
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout.strip(), 0.0
    if not isinstance(data, dict):
        return stdout.strip(), 0.0
    text = data.get("result") or data.get("text") or ""
    try:
        cost = float(data.get("total_cost_usd") or data.get("cost_usd") or 0.0)
    except (ValueError, TypeError):
        cost = 0.0
    return str(text).strip(), cost
