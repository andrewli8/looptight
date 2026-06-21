from __future__ import annotations

import json
import socket
import subprocess

from looptight.claims import ClaimStore, claim_dir, owner_id


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


def test_corrupt_non_string_task_id_is_treated_as_stale(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text(
        json.dumps(
            {"schema_version": 1, "task_id": ["not", "a", "string"],
             "owner": "session", "claimed_at": 100},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    task = _task("one")

    selected = ClaimStore(tmp_path, "session", now=101).select([task])

    assert selected == task
    assert not corrupt.exists()


def test_summary_reads_claims_without_mutating_them(tmp_path):
    tasks = [_task("one"), _task("two")]
    ClaimStore(tmp_path, "session-a", now=100).select(tasks)
    ClaimStore(tmp_path, "session-b", now=100).select(tasks)
    before = {path: path.read_text() for path in tmp_path.glob("*.json")}

    owned, active = ClaimStore(tmp_path, "session-a", now=101).summary()

    assert (owned, active) == ("one", 2)
    assert {path: path.read_text() for path in tmp_path.glob("*.json")} == before


def test_owner_id_prefers_explicit_session_id(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPTIGHT_SESSION_ID", "ci-session-7")

    assert owner_id(tmp_path) == "ci-session-7"


def test_owner_id_defaults_to_host_and_resolved_path(tmp_path, monkeypatch):
    monkeypatch.delenv("LOOPTIGHT_SESSION_ID", raising=False)

    assert owner_id(tmp_path) == f"{socket.gethostname()}:{tmp_path.resolve()}"


def test_claim_dir_uses_git_private_state(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = claim_dir(tmp_path)

    assert path is not None
    assert path == (tmp_path / ".git" / "looptight" / "claims").resolve()
