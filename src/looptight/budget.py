"""Budget + iteration accounting (D1).

Low defaults, a hard stop, and a single object the loop and the live counter
both read. A default run cannot exceed the cost ceiling without an explicit
``--budget`` (which the CLI surfaces as the only way to raise it).
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
        return self.spent_usd >= self.budget_usd
