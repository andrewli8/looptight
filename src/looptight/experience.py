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

__all__ = [
    "Model", "build_model", "landed_counts", "landed_category_counts",
    "suppressed", "reweight_factor", "summary_text",
]

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


def landed_category_counts(root: Path, target_ref: str, *, limit: int = 500) -> dict[str, int]:
    """Verified-landed counts per task source (category), from `<idea> landed <source>`
    trailers reachable from target_ref. Trailers without a source token are skipped."""
    result = _git(
        root, "log", target_ref, f"-n{limit}", f"--grep={_OUTCOME_KEY}",
        "--pretty=%(trailers:key=Looptight-Outcome,valueonly)",
    )
    if result.returncode != 0:
        return {}
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "landed":
            counts[parts[2]] = counts.get(parts[2], 0) + 1
    return counts


@dataclass(frozen=True)
class Model:
    landed: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    category_landed: dict[str, int] = field(default_factory=dict)
    category_failed: dict[str, int] = field(default_factory=dict)
    category_failure_reasons: dict[str, str] = field(default_factory=dict)


def build_model(
    root: Path, target_ref: str, coordinator, *,
    cooldown_s: float, now: float | None = None, limit: int = 500,
) -> Model:
    """Union verified-landed (git) and recent local failures (coordinator)."""
    landed = landed_counts(root, target_ref, limit=limit)
    category_landed = landed_category_counts(root, target_ref, limit=limit)
    failed = coordinator.recent_failures(window_s=cooldown_s, now=now) if coordinator else {}
    category_failed = coordinator.failure_counts() if coordinator else {}
    category_failure_reasons = coordinator.failure_reasons() if coordinator else {}
    return Model(
        landed=landed, failed=failed,
        category_landed=category_landed, category_failed=category_failed,
        category_failure_reasons=category_failure_reasons,
    )


def suppressed(model: Model, *, max_failures: int = 2) -> set[str]:
    """Idea ids whose recent failures reached the cooldown threshold."""
    return {idea for idea, n in model.failed.items() if n >= max_failures}


def reweight_factor(category: str, model: Model, *, lo: float = 0.5, hi: float = 1.5) -> float:
    """Clamped yield multiplier for a category; 1.0 when there is no data."""
    landed = model.category_landed.get(category, 0)
    failed = model.category_failed.get(category, 0)
    total = landed + failed
    if total == 0:
        return 1.0
    rate = max(0.0, min(1.0, landed / total))  # clamp against malformed counts
    return lo + (hi - lo) * rate


def summary_text(model: Model, *, k: int = 5) -> str:
    """A bounded experience note for the planner, or '' when there is nothing useful."""
    if not model.failed and not model.landed and not model.category_failure_reasons:
        return ""
    lines: list[str] = []
    if model.failed:
        avoid = sorted(model.failed, key=lambda i: model.failed[i], reverse=True)[:k]
        lines.append("Recently-failed ideas to avoid re-proposing: " + ", ".join(avoid) + ".")
    if model.landed:
        top = sorted(model.landed, key=lambda i: model.landed[i], reverse=True)[:k]
        lines.append("Recently-landed idea kinds that paid off: " + ", ".join(top) + ".")
    if model.category_failure_reasons:
        modes = ", ".join(
            f"{category} often fails on {reason}"
            for category, reason in sorted(model.category_failure_reasons.items())[:k]
        )
        lines.append("Common failure modes by source: " + modes + ".")
    return "\n".join(lines)
