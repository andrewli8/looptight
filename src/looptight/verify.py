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

from .proctree import new_process_group_kwargs, stop_process_tree
from .types import VerifyResult

_SCORE_RE = re.compile(r"^\s*SCORE:\s*([-+]?\d*\.?\d+)\s*$", re.MULTILINE)

# Keep verifier evidence bounded for terminal and JSON consumers.
_MAX_OUTPUT_CHARS = 8000


def parse_score(output: str | None) -> float | None:
    """Return the last ``SCORE: <n>`` value in the output, if any.

    ``None`` output is treated as empty (the ``output or ""`` fallback), so a
    missing capture yields ``None`` rather than raising.
    """
    matches = _SCORE_RE.findall(output or "")
    return float(matches[-1]) if matches else None


_TRUNCATION_MARK = "\n...[truncated]...\n"


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    # The separator counts against the budget so the result never exceeds the cap.
    half = (_MAX_OUTPUT_CHARS - len(_TRUNCATION_MARK)) // 2
    return f"{text[:half]}{_TRUNCATION_MARK}{text[-half:]}"


def _as_text(value: str | bytes | None) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else value or ""


def _timeout_output(partial: str, command: str, timeout_s: float) -> str:
    """Retain output captured before a timeout so the next iteration can act on it."""
    separator = "\n" if partial and not partial.endswith("\n") else ""
    return _truncate(f"{partial}{separator}verify timed out after {timeout_s:g}s: {command}")


def run_verify(
    command: str,
    cwd: Path | None = None,
    timeout_s: float = 600.0,
) -> VerifyResult:
    """Execute ``command`` in a shell and capture its verdict.

    A timeout or launch failure is treated as a (recoverable) failure, never a
    crash — the loop should keep its footing and let the agent try again.
    """
    if not command or not command.strip():
        # A blank command runs a no-op shell that exits 0 — never treat that as a pass, since
        # verify is the only commit authority. Defense-in-depth behind config's blank-verify guard.
        return VerifyResult(
            passed=False,
            exit_code=2,
            output="verify command is blank; refusing to treat a no-op as a pass",
            error="blank_verify",
        )
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",  # verify output is untrusted bytes; never crash on bad UTF-8
            **new_process_group_kwargs(),
        )
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        stop_process_tree(proc)
        stdout, stderr = proc.communicate()
        partial = _as_text(stdout) + _as_text(stderr)
        return VerifyResult(
            passed=False,
            exit_code=124,
            output=_timeout_output(partial, command, timeout_s),
            score=parse_score(partial),
            duration_s=time.monotonic() - started,
            error="timeout",
        )
    except OSError as exc:
        return VerifyResult(
            passed=False,
            exit_code=127,
            output=f"could not run verify command: {exc}",
            duration_s=time.monotonic() - started,
            error="launch_error",
        )

    combined = (stdout or "") + (stderr or "")
    launch_error = "launch_error" if proc.returncode in (126, 127) else None
    # Parse the score from the full output, then store a bounded copy: a SCORE
    # line in the truncated-away middle would otherwise be silently lost.
    return VerifyResult(
        passed=proc.returncode == 0,
        exit_code=proc.returncode,
        output=_truncate(combined),
        score=parse_score(combined),
        duration_s=time.monotonic() - started,
        error=launch_error,
    )
