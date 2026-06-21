"""Stable task identity contracts."""

from __future__ import annotations

import subprocess

from looptight.propose import Candidate
from looptight.tasks import next_task


def test_task_id_is_stable_when_discovery_route_changes(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

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
