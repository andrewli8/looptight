"""Shared, dependency-free prompts for grounded idea generation.

One source of truth for the planning prompt, used by both the swarm planner
subagent (`swarm.plan_next_tasks`) and the session-native on-empty directive
surfaced by `next`. Keeping it here avoids importing the swarm's heavy module
(adapters, loop, verify) just to reach the text.
"""

from __future__ import annotations

from .experience import Model, summary_text

#: Action name the `next` no-work directive carries so a host agent knows what to
#: do without parsing prose.
IDEA_DIRECTIVE_ACTION = "generate_ideas"

#: The planning manager prompt. Its grounding rail — "if no necessary improvement
#: is supported by repository evidence, make no changes" — is what keeps idea
#: generation honest (evidence-backed, terminating) rather than inventing work.
PLANNING_GOAL = """Act as the planning manager for this repository.
Inspect the implementation, tests, verifier output, and docs/STATUS.md.
Survey the repository through several independent reviewer lenses in turn
(test coverage; error handling and input validation; spec and docs conformance;
performance; dead or duplicated code), gather candidate tasks from each lens on its
own, then merge duplicates and keep only the most necessary, so the lenses widen
coverage without inflating the list. Update only the bounded `## Next` section of
docs/STATUS.md with 1-6 necessary, evidence-backed tasks. Every numbered item must
include `Evidence: relative/path[:line];` pointing to an existing repository file and
an `Acceptance:` clause with an observable outcome; prefer framing each task so its
Acceptance is a single new failing-then-passing test, or an outcome provable by
diffing one named file. Replace stale items; do not append a changelog, implement
tasks, or edit any other file or run Git commands. If no necessary improvement is
supported by repository evidence, make no changes."""

# Anchor on the START of the grounding-rail sentence. PLANNING_GOAL wraps that
# sentence across a newline, so we split on the sentence start and keep the rail
# verbatim rather than matching its exact (newline-containing) text.
_RAIL_ANCHOR = "If no necessary improvement"


def planning_goal(model: Model | None = None) -> str:
    """PLANNING_GOAL, optionally with a bounded experience note before the rail."""
    note = summary_text(model) if model is not None else ""
    if not note:
        return PLANNING_GOAL
    idx = PLANNING_GOAL.rindex(_RAIL_ANCHOR)
    head = PLANNING_GOAL[:idx].rstrip()
    rail = PLANNING_GOAL[idx:]
    return f"{head}\n\nLearned from past runs:\n{note}\n\n{rail}"
