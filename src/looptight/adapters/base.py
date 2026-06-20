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

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from ..types import IterationResult


def run_command(cmd: list[str], workdir: Path) -> subprocess.CompletedProcess[str]:
    """Run an agent CLI, normalizing launch failures as a non-zero result."""
    try:
        return subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            errors="replace",  # agent CLI output is untrusted bytes; never crash on bad UTF-8
            check=False,
        )
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
    #: True when iteration results include measured USD cost.
    reports_cost_usd: bool = False

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
        budget_usd: float,
        workdir: Path,
    ) -> IterationResult:
        """Drive the agent's own eval-gated loop to completion (delegate mode).

        Only implemented when ``supports_native_loop`` is True. Returns the final
        transcript + cost; looptight still runs ``verify`` afterward as the
        contract (principle 2).
        """
        raise NotImplementedError(f"{self.name} has no native loop to drive")
