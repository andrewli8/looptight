"""Task proposal — compose discovery and ranking into a candidate list.

`propose` is the grounded half of "what to work on": it discovers verifiable
signals (``discovery.py``), dedupes and ranks them (``ranking.py``), and returns
the top candidates. It runs no agent, spends no tokens, and writes nothing.

Discovery and ranking live in their own modules so each stays a single concern;
this module only wires them together and re-exports :class:`Candidate`, the
public type its result is made of.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config, find_config, load_config
from .coordinator import Coordinator
from .discovery import Candidate, discover
from .experience import Model, build_model, suppressed
from .idea_identity import idea_id
from .ranking import dedupe, rank, rank_with_model

__all__ = ["Candidate", "propose"]

_COOLDOWN_S = 24 * 3600.0
_MAX_FAILURES = 2


def _apply_cooldown(candidates: list[Candidate], model: Model, *, max_failures: int) -> list[Candidate]:
    """Drop candidates whose idea is in cooldown. Pure; no-op on an empty model."""
    blocked = suppressed(model, max_failures=max_failures)
    if not blocked:
        return candidates
    return [c for c in candidates if idea_id(c) not in blocked]


def propose(root: Path, *, limit: int = 10) -> list[Candidate]:
    """Scan all signals, dedupe, rank, suppress cooled-down ideas, return the top N."""
    config_path = find_config(root)
    config = load_config(config_path) if config_path else Config()
    discovery_root = config_path.parent if config_path else root
    coordinator = Coordinator.open(discovery_root)
    if coordinator is not None:
        try:
            model = build_model(discovery_root, "HEAD", coordinator, cooldown_s=_COOLDOWN_S)
            base = dedupe(discover(discovery_root, task_files=config.tasks))
            ranked = _apply_cooldown(rank_with_model(base, model), model, max_failures=_MAX_FAILURES)
        finally:
            coordinator.close()
    else:
        ranked = rank(dedupe(discover(discovery_root, task_files=config.tasks)))

    return ranked[:limit] if limit and limit > 0 else ranked
