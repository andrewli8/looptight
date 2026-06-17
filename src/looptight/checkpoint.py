"""Per-iteration git checkpoints + revert (D4).

"I can always get my repo back." Before each iteration we snapshot the working
tree into a dangling commit object using ``git stash create`` — this captures
tracked changes without touching the index, the working tree, or the branch.
Restoring checks that tree back out. If we're not in a git repo, checkpointing
degrades to a no-op (the loop still runs; it just can't offer restore points).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(cwd: Path) -> bool:
    result = _git(["rev-parse", "--is-inside-work-tree"], cwd)
    return result.returncode == 0 and result.stdout.strip() == "true"


@dataclass
class Checkpointer:
    """Captures and restores working-tree snapshots for one run."""

    cwd: Path
    enabled: bool = True
    snapshots: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.enabled and not is_git_repo(self.cwd):
            self.enabled = False

    def snapshot(self) -> str | None:
        """Capture the current working tree. Returns a commit sha, or None."""
        if not self.enabled:
            return None
        # `stash create` builds a commit from current changes without altering
        # anything. With a clean tree it prints nothing, so fall back to HEAD.
        created = _git(["stash", "create", "looptight checkpoint"], self.cwd)
        sha = created.stdout.strip()
        if not sha:
            head = _git(["rev-parse", "HEAD"], self.cwd)
            sha = head.stdout.strip()
        if sha:
            self.snapshots.append(sha)
            return sha
        return None

    def restore(self, sha: str | None = None) -> bool:
        """Restore the working tree to ``sha`` (default: the latest snapshot)."""
        if not self.enabled:
            return False
        target = sha or (self.snapshots[-1] if self.snapshots else None)
        if not target:
            return False
        result = _git(["checkout", target, "--", "."], self.cwd)
        return result.returncode == 0

    def diffstat(self, since: str | None = None) -> str:
        """A short diffstat from the first snapshot to the working tree (E1)."""
        if not self.enabled:
            return ""
        base = since or (self.snapshots[0] if self.snapshots else None)
        if not base:
            return ""
        result = _git(["diff", "--stat", base], self.cwd)
        return result.stdout.strip()
