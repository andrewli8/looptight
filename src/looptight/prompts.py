"""Shared, dependency-free prompts for grounded idea generation.

One source of truth for the planning prompt, used by both the swarm planner
subagent (`swarm.plan_next_tasks`) and the session-native on-empty directive
surfaced by `next`. Keeping it here avoids importing the swarm's heavy module
(adapters, loop, verify) just to reach the text.
"""

from __future__ import annotations

#: Action name the `next` no-work directive carries so a host agent knows what to
#: do without parsing prose.
IDEA_DIRECTIVE_ACTION = "generate_ideas"

#: The planning manager prompt. Its grounding rail — "if no necessary improvement
#: is supported by repository evidence, make no changes" — is what keeps idea
#: generation honest (evidence-backed, terminating) rather than inventing work.
PLANNING_GOAL = """Act as the planning manager for this repository.
Inspect the implementation, tests, verifier output, and docs/STATUS.md. Update only
the bounded `## Next` section of docs/STATUS.md with 1-6 necessary, evidence-backed
tasks. Every numbered item must include `Evidence: relative/path[:line];` pointing to
an existing repository file and an `Acceptance:` clause with an observable outcome.
Replace stale items; do not append a changelog, implement tasks, or edit any other
file or run Git commands. If no necessary improvement is supported by repository
evidence, make no changes."""
