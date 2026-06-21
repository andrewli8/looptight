"""The shared planning prompt — one source for swarm and the next directive."""

from __future__ import annotations

from looptight.prompts import IDEA_DIRECTIVE_ACTION, PLANNING_GOAL


def test_planning_goal_is_grounded_and_bounded():
    assert "docs/STATUS.md" in PLANNING_GOAL
    assert "Evidence:" in PLANNING_GOAL
    assert "Acceptance:" in PLANNING_GOAL
    # The grounding rail that keeps idea generation honest and terminating.
    assert "make no changes" in PLANNING_GOAL


def test_swarm_reuses_the_shared_planning_goal():
    from looptight import swarm

    assert swarm.PLANNING_GOAL is PLANNING_GOAL


def test_idea_directive_action_is_stable():
    assert IDEA_DIRECTIVE_ACTION == "generate_ideas"
