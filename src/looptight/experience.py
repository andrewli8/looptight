"""The self-model: what looptight has learned from past idea outcomes.

Positive signal (`landed`) is read from git history, structurally verified: only
commits reachable from the target ref are scanned, so a trailer on an unmerged
commit never counts. Negative signal (`failed`) is read from the repo-private
coordinator. The model is advisory; callers degrade to default behavior if it is
empty or unavailable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Model", "build_model", "landed_counts"]

_OUTCOME_KEY = "Looptight-Outcome:"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=str(root),
                              capture_output=True, text=True, check=False)
    except OSError as exc:
        return subprocess.CompletedProcess(["git", *args], 127, "", str(exc))


def landed_counts(root: Path, target_ref: str, *, limit: int = 500) -> dict[str, int]:
    """Verified-landed counts per idea_id, from trailers reachable from target_ref."""
    result = _git(
        root, "log", target_ref, f"-n{limit}", f"--grep={_OUTCOME_KEY}",
        "--pretty=%(trailers:key=Looptight-Outcome,valueonly)",
    )
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "landed" not in line:
            continue
        idea = line.split()[0]
        counts[idea] = counts.get(idea, 0) + 1
    return counts


@dataclass(frozen=True)
class Model:
    landed: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    category_landed: dict[str, int] = field(default_factory=dict)
    category_failed: dict[str, int] = field(default_factory=dict)


def build_model(
    root: Path, target_ref: str, coordinator, *,
    cooldown_s: float, now: float | None = None, limit: int = 500,
) -> Model:
    """Union verified-landed (git) and recent local failures (coordinator)."""
    landed = landed_counts(root, target_ref, limit=limit)
    failed = coordinator.recent_failures(window_s=cooldown_s, now=now) if coordinator else {}
    category_failed = coordinator.failure_counts() if coordinator else {}
    return Model(landed=landed, failed=failed, category_failed=category_failed)
