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


def test_planning_goal_unchanged_without_model():
    from looptight.experience import Model
    from looptight.prompts import planning_goal

    assert planning_goal(None) == PLANNING_GOAL
    assert planning_goal(Model()) == PLANNING_GOAL


def test_planning_goal_injects_summary_before_grounding_rail():
    from looptight.experience import Model
    from looptight.prompts import planning_goal

    m = Model(failed={"idea-x": 2})
    text = planning_goal(m)
    assert "idea-x" in text
    # the grounding rail stays the final instruction
    assert text.rstrip().endswith("make no changes.")
