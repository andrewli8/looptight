"""Budget + iteration accounting (D1).

Low defaults, a clean stop, and a single object the loop and the live counter
both read. Cost is known only after each agent call, so ``budget_usd`` is a
spend threshold checked between iterations: the loop stops once spend reaches
or exceeds it, and a single iteration can overshoot. ``--budget`` raises it above the safe
default.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetTracker:
    """Tracks spend and iteration count against hard caps."""

    max_iterations: int
    budget_usd: float
    spent_usd: float = 0.0
    iteration: int = 0

    def start_iteration(self) -> int:
        """Advance the counter and return the new (1-based) iteration number."""
        self.iteration += 1
        return self.iteration

    def add_cost(self, cost_usd: float) -> None:
        self.spent_usd += max(0.0, cost_usd)

    def over_budget(self) -> bool:
        """True once spend reaches the threshold (checked after each iteration)."""
        return self.spent_usd >= self.budget_usd
