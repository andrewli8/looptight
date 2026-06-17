"""The ground-truth oracle (B3).

Runs the user's verify command and turns it into a ``VerifyResult``. Pass/fail
is the exit code. An optional numeric score is parsed from a ``SCORE: <n>`` line
so the same machinery supports score-gated loops, not just pass/fail.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .types import VerifyResult

_SCORE_RE = re.compile(r"^\s*SCORE:\s*([-+]?\d*\.?\d+)\s*$", re.MULTILINE)

# Keep transcripts bounded so summaries and reflection prompts stay cheap.
_MAX_OUTPUT_CHARS = 8000


def parse_score(output: str) -> float | None:
    """Return the last ``SCORE: <n>`` value in the output, if any."""
    matches = _SCORE_RE.findall(output or "")
    return float(matches[-1]) if matches else None


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    half = _MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n...[truncated]...\n{text[-half:]}"


def run_verify(
    command: str,
    cwd: Path | None = None,
    timeout_s: float = 600.0,
) -> VerifyResult:
    """Execute ``command`` in a shell and capture its verdict.

    A timeout or launch failure is treated as a (recoverable) failure, never a
    crash — the loop should keep its footing and let the agent try again.
    """
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            passed=False,
            exit_code=124,
            output=f"verify timed out after {timeout_s:g}s: {command}",
            duration_s=time.monotonic() - started,
        )
    except OSError as exc:
        return VerifyResult(
            passed=False,
            exit_code=127,
            output=f"could not run verify command: {exc}",
            duration_s=time.monotonic() - started,
        )

    output = _truncate((proc.stdout or "") + (proc.stderr or ""))
    return VerifyResult(
        passed=proc.returncode == 0,
        exit_code=proc.returncode,
        output=output,
        score=parse_score(output),
        duration_s=time.monotonic() - started,
    )
