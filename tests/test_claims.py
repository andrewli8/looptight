from __future__ import annotations

import json
import subprocess

from looptight.claims import ClaimStore, claim_dir


def _task(task_id: str) -> dict[str, str | None]:
    return {
        "id": task_id,
        "source": "status-next",
        "location": "docs/STATUS.md",
        "goal": f"do {task_id}",
        "evidence": "",
        "suggested_verify": None,
    }


def test_claims_are_atomic_across_owners_and_stable_for_owner(tmp_path):
    tasks = [_task("one"), _task("two")]
    first = ClaimStore(tmp_path, "session-a", now=100).select(tasks)
    same = ClaimStore(tmp_path, "session-a", now=101).select(tasks)
    second = ClaimStore(tmp_path, "session-b", now=101).select(tasks)

    assert first == same == tasks[0]
    assert second == tasks[1]
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_stale_claim_can_be_recovered(tmp_path):
    task = _task("one")
    ClaimStore(tmp_path, "gone", now=0).select([task])

    recovered = ClaimStore(tmp_path, "new", now=24 * 60 * 60 + 1).select([task])

    assert recovered == task
    claim = json.loads((tmp_path / "one.json").read_text())
    assert claim["owner"] == "new"


def test_claim_disappears_when_task_is_no_longer_grounded(tmp_path):
    old = _task("old")
    new = _task("new")
    ClaimStore(tmp_path, "session", now=100).select([old])

    assert ClaimStore(tmp_path, "session", now=101).select([new]) == new
    assert not (tmp_path / "old.json").exists()


def test_claim_dir_uses_git_private_state(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = claim_dir(tmp_path)

    assert path is not None
    assert path == (tmp_path / ".git" / "looptight" / "claims").resolve()
