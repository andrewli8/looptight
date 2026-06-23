"""The shared planning prompt — one source for swarm and the next directive."""

from __future__ import annotations

from looptight.prompts import IDEA_DIRECTIVE_ACTION, PLANNING_GOAL


def test_planning_goal_is_grounded_and_bounded():
    assert "docs/STATUS.md" in PLANNING_GOAL
    assert "Evidence:" in PLANNING_GOAL
    assert "Acceptance:" in PLANNING_GOAL
    # The grounding rail that keeps idea generation honest and terminating.
    assert "make no changes" in PLANNING_GOAL


def test_planning_goal_uses_multiple_reviewer_lenses_and_constraint_framing():
    # Multi-view generation: survey the repo under several independent reviewer lenses
    # then merge duplicates, widening coverage without inflating the bounded list
    # (Diehl & Stroebe 1987 nominal>real groups; Si et al. 2024 LLM diversity ceiling).
    assert "reviewer lenses" in PLANNING_GOAL
    for lens in ("test", "error handling", "performance"):
        assert lens in PLANNING_GOAL
    assert "merge duplicates" in PLANNING_GOAL
    # Constraints-as-scaffold: push the grounding constraint upstream into the
    # generation framing, not only the downstream reject gate (Haught-Tromp 2017).
    assert "failing-then-passing test" in PLANNING_GOAL
    # Widening coverage must not break the bound or move the grounding rail.
    assert "1-6" in PLANNING_GOAL
    assert PLANNING_GOAL.rstrip().endswith("make no changes.")


def test_planning_goal_seeds_ideas_by_analogy_when_signals_run_dry():
    # Analogical transfer keeps discovery productive on repos lacking surface signals:
    # map a recently-improved file onto sibling modules that lack the same treatment,
    # both grounded as evidence (Gick & Holyoak 1980/1983; Mednick 1962). The grounding
    # gate still catches false analogies, so this widens discovery without ungrounding it.
    assert "by analogy" in PLANNING_GOAL
    assert "sibling" in PLANNING_GOAL


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
