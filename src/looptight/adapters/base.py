"""The adapter interface (F1).

Every supported agent is exactly one adapter. The model is deliberately small:

- **Every adapter can *supply* a loop iteration** — `run_iteration` runs the
  agent once, headless, and reports what it did. looptight wraps
  this in run → verify → continue. This is the universal path; all three agents
  have a confirmed headless one-shot mode, so "one interface, three agents" is
  literally true.
- **An adapter *may* also drive the agent's own native loop** (e.g. Claude
  Code's `/goal`). It sets ``supports_native_loop = True`` and implements
  ``drive_native_loop``. This is opt-in via ``--native``.

Either way, **`verify` stays the ground-truth oracle** (principle 2): looptight
runs the verify command itself. Adding an agent means writing one subclass and
registering it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from ..limits import classify_limit, format_limit_error
from ..types import IterationResult

_ACTIVE_PROCESSES: set[subprocess.Popen[str]] = set()
_ACTIVE_LOCK = threading.Lock()


def failure_iteration(
    proc: subprocess.CompletedProcess[str], name: str
) -> IterationResult:
    """Map a non-zero provider invocation to an ``IterationResult``.

    Three cases, shared by every supply-path adapter: a timeout (code 124) keeps
    the timeout message so the swarm can tag it; a provider-reported usage/rate
    limit is surfaced with a stable marker so the continuous swarm can wait it out
    and resume; anything else is a generic non-zero failure.
    """
    stderr = (proc.stderr or "").strip()
    if proc.returncode == 124:
        return IterationResult(transcript=stderr or f"{name} timed out", ok=False, error=stderr)
    signal = classify_limit(f"{proc.stdout or ''}\n{proc.stderr or ''}")
    if signal is not None:
        return IterationResult(
            transcript=stderr or f"{name} reported a usage limit",
            ok=False,
            error=format_limit_error(signal),
        )
    return IterationResult(
        transcript=stderr or f"{name} exited non-zero",
        ok=False,
        error=f"{name} exited {proc.returncode}",
    )


def _stop_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except OSError:
            pass
    elif os.name == "nt":
        try:
            stopped = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
            if stopped.returncode == 0:
                return
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def stop_active_processes() -> None:
    """Terminate provider process trees owned by this Looptight process."""
    with _ACTIVE_LOCK:
        active = tuple(_ACTIVE_PROCESSES)
    for process in active:
        _stop_process_tree(process)


def run_command(
    cmd: list[str], workdir: Path, *, timeout_s: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an agent CLI, normalizing launch failures as a non-zero result."""
    try:
        if timeout_s is None:
            return subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
        options: dict[str, object] = {}
        if os.name == "posix":
            options["start_new_session"] = True
        elif os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            cmd,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            **options,
        )
        with _ACTIVE_LOCK:
            _ACTIVE_PROCESSES.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                _stop_process_tree(process)
                stdout, stderr = process.communicate()
                message = f"provider timed out after {timeout_s:g}s"
                stderr = f"{stderr.rstrip()}\n{message}" if stderr else message
                return subprocess.CompletedProcess(cmd, 124, stdout, stderr)
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_PROCESSES.discard(process)
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except OSError as exc:
        return subprocess.CompletedProcess(
            cmd, 127, stdout="", stderr=f"could not launch {cmd[0]}: {exc}"
        )


class Adapter(ABC):
    """Base class for an agent integration."""

    #: CLI/registry name, e.g. ``"claude"``.
    name: str = ""
    #: Memory file the agent reads automatically, relative to the project root.
    memory_filename: str = "AGENTS.md"
    #: True if the agent ships a headless eval-gated loop we can drive (B1).
    supports_native_loop: bool = False
    worker_timeout_s: float | None = None

    @abstractmethod
    def is_available(self) -> bool:
        """True if the agent's CLI is installed and usable. Auth-neutral (A4) —
        we never check *which* auth, only that the agent can run."""

    def memory_file(self, workdir: Path) -> Path:
        """Path to the agent's native memory file (C2)."""
        return workdir / self.memory_filename

    @abstractmethod
    def run_iteration(
        self,
        goal: str,
        context: str,
        workdir: Path,
        model: str | None = None,
    ) -> IterationResult:
        """Run one headless coding iteration (supply mode)."""

    def drive_native_loop(
        self,
        goal: str,
        verify: str,
        max_iterations: int,
        workdir: Path,
    ) -> IterationResult:
        """Drive the agent's own eval-gated loop to completion (delegate mode).

        Only implemented when ``supports_native_loop`` is True. Returns the final
        transcript; looptight still runs ``verify`` afterward as the contract.
        """
        raise NotImplementedError(f"{self.name} has no native loop to drive")
