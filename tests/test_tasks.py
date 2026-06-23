"""Stable task identity contracts."""

from __future__ import annotations

import subprocess

from looptight.propose import Candidate
from looptight.tasks import _summary_and_evidence, next_task


def _candidate(title: str, detail: str) -> Candidate:
    return Candidate(
        title=title,
        source="status-next",
        location="docs/STATUS.md:5",
        suggested_verify=None,
        score=0.0,
        detail=detail,
        acceptance="it passes.",
    )


def test_summary_and_evidence_splits_inline_evidence():
    candidate = _candidate(
        "Cover the parser. Evidence: src/p.py:3",
        "Cover the parser. Evidence: src/p.py:3; Acceptance: it passes.",
    )
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "Cover the parser"  # refs stripped from the summary
    assert evidence == "Evidence: src/p.py:3"


def test_summary_and_evidence_preserves_multiple_refs():
    candidate = _candidate(
        "Do the thing. Evidence: src/a.py:1; Evidence: tests/test_a.py:2",
        "Do the thing. Evidence: src/a.py:1; Evidence: tests/test_a.py:2; Acceptance: it passes.",
    )
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "Do the thing"
    assert evidence == "Evidence: src/a.py:1; Evidence: tests/test_a.py:2"


def test_summary_and_evidence_falls_back_to_detail_without_marker():
    # Ad-hoc signals (todo/lint) carry no inline marker; their detail is the evidence.
    candidate = _candidate("# TODO: fix the timeout", "# TODO: fix the timeout")
    summary, evidence = _summary_and_evidence(candidate)
    assert summary == "# TODO: fix the timeout"
    assert evidence == "# TODO: fix the timeout"


def test_next_task_attaches_idea_id(tmp_path):
    cand = Candidate(title="fix E501: line too long", source="lint",
                     location="src/looptight/foo.py:10", suggested_verify=None,
                     score=60.0, detail="line too long", acceptance="ruff clean")

    def fake_propose(workdir, limit=0):
        return [cand]

    result = next_task(tmp_path, propose_fn=fake_propose)
    assert result.status == "task"
    from looptight.idea_identity import idea_id
    assert result.task["idea_id"] == idea_id(cand)


def test_task_id_is_stable_when_discovery_route_changes(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # One logical session (stable run id) re-claims its own lease, so the second
    # call returns the same task and we can assert fingerprint stability across
    # discovery routes rather than tripping over the coordinator's distinct-run fencing.
    monkeypatch.setenv("LOOPTIGHT_RUN_ID", "stable-session")

    def candidate(source):
        return Candidate(
            title="Fix the same task",
            source=source,
            location="docs/STATUS.md:10",
            suggested_verify=None,
            score=0.0,
            detail="same evidence",
            acceptance="same acceptance",
        )

    first = next_task(tmp_path, propose_fn=lambda root, limit: [candidate("status-next")])
    second = next_task(tmp_path, propose_fn=lambda root, limit: [candidate("task-file")])

    assert first.task is not None and second.task is not None
    assert first.task["id"] == second.task["id"]
    assert second.task["source"] == "task-file"
