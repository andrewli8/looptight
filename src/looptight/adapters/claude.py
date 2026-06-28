"""Claude Code adapter.

Claude Code has both a headless one-shot mode (``claude -p``) and a native
eval-gated loop (``/goal``, shipped 2026), so this adapter does both:

- **supply** (default): each iteration runs ``claude -p <prompt> --output-format
  json`` and read its result.
- **delegate** (``--native``): drive ``claude -p "/goal …"`` and let Claude's own
  Haiku evaluator gate the condition. looptight still runs ``verify`` afterward
  as the contract.

Auth-neutral (A4): we invoke whatever ``claude`` is on PATH and let it use its
existing auth. Claude Code auto-loads ``CLAUDE.md``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from subprocess import CompletedProcess

from ..limits import classify_limit, format_limit_error
from ..types import IterationResult
from .base import Adapter, failure_iteration, run_command

class ClaudeAdapter(Adapter):
    name = "claude"
    memory_filename = "CLAUDE.md"
    supports_native_loop = True

    binary = "claude"

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def _invoke(
        self, prompt: str, workdir: Path, model: str | None
    ) -> CompletedProcess[str]:
        cmd = [self.binary, "-p", prompt, "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        return run_command(cmd, workdir, timeout_s=self.worker_timeout_s)

    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        proc = self._invoke(_build_prompt(goal, context), workdir, model)
        if proc.returncode != 0:
            return failure_iteration(proc, self.name)
        return IterationResult(transcript=_parse_result(proc.stdout), ok=True)

    def drive_native_loop(
        self,
        goal: str,
        verify: str,
        max_iterations: int,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        prompt = (
            f"/goal {goal}. Keep going until the command `{verify}` exits with "
            f"status 0. Stop after at most {max_iterations} attempts."
        )
        proc = self._invoke(prompt, workdir, model)
        transcript = _parse_result(proc.stdout)
        if proc.returncode == 0:
            return IterationResult(transcript=transcript, ok=True)
        if not transcript:
            transcript = proc.stderr.strip() or f"claude /goal exited {proc.returncode}"
        # A usage/rate limit during the native loop must carry the stable marker so
        # the delegate loop's --resume-on-limit can wait it out and retry, exactly
        # as the supply path does via failure_iteration. A non-limit failure keeps
        # error unset so the loop surfaces the transcript and does not spin.
        signal = classify_limit(f"{proc.stdout or ''}\n{proc.stderr or ''}")
        error = format_limit_error(signal) if signal is not None else None
        return IterationResult(
            transcript=transcript, ok=False, error=error, returncode=proc.returncode
        )

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


def _parse_result(stdout: str) -> str:
    """Pull result text out of Claude Code's JSON output."""
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout.strip()
    if not isinstance(data, dict):
        return stdout.strip()
    text = data.get("result") or data.get("text") or ""
    return str(text).strip()
