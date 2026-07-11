from __future__ import annotations

import json
import socket
import subprocess
from unittest.mock import patch

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


def test_claim_with_non_numeric_timestamp_is_treated_as_expired(tmp_path):
    # A corrupt claim whose claimed_at is not a number must not crash next/status:
    # an unreadable timestamp is treated as expired (pruned), never raising.
    (tmp_path / "t1.json").write_text(
        json.dumps(
            {"schema_version": 1, "task_id": "t1", "owner": "x", "claimed_at": "oops"}
        ),
        encoding="utf-8",
    )
    # now is well past the staleness window, so a 0.0 fallback reads as expired.
    store = ClaimStore(tmp_path, "me", now=1_000_000_000.0)

    assert store.summary() == (None, 0)  # not counted as live, no crash

    task = _task("t1")
    assert store.select([task]) == task  # the stale claim is reclaimed, not fatal


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


def test_claim_dir_returns_none_on_oserror(tmp_path, monkeypatch):
    import looptight.claims as claims_mod

    monkeypatch.setattr(claims_mod.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(OSError("no git")))
    assert claim_dir(tmp_path) is None


def test_has_live_claim_returns_false_when_root_absent(tmp_path):
    # claims.py:34 — `if not claims_root.is_dir(): return False` is the guard for
    # a directory that does not exist.  Both sibling tests create root.mkdir() before
    # calling has_live_claim, so this early-exit path is untested and a mutation
    # removing or inverting the guard would go undetected.
    from looptight.claims import has_live_claim

    absent = tmp_path / "nonexistent"
    assert has_live_claim(absent) is False  # directory does not exist -> False immediately


def test_claimed_at_null_is_treated_as_expired(tmp_path):
    # claims.py:20 — `float(claim.get("claimed_at", 0))` raises TypeError when the JSON
    # field holds null (get() returns None, not the default 0).  The `except (TypeError,
    # ValueError)` handler returns 0.0 (long-expired).  Only the ValueError sub-path is
    # exercised by test_claim_with_non_numeric_timestamp_is_treated_as_expired (which uses
    # "claimed_at": "oops"), leaving the TypeError arm untested — the same gap pattern
    # that test_record_treats_null_updated_at_as_stale covers in trajectory.py:72.
    from looptight.claims import has_live_claim

    root = tmp_path / "claims"
    root.mkdir()
    (root / "t1.json").write_text(
        json.dumps({"schema_version": 1, "task_id": "t1", "owner": "x", "claimed_at": None}),
        encoding="utf-8",
    )
    # A null claimed_at falls back to 0.0 (long expired); no live claim, no crash.
    assert has_live_claim(root, now=1_000_000_000.0) is False
    # summary() must similarly treat null claimed_at as expired (active count stays 0).
    assert ClaimStore(root, "me", now=1_000_000_000.0).summary() == (None, 0)


def test_has_live_claim_false_when_all_claims_expired(tmp_path):
    from looptight.claims import _STALE_AFTER_S, has_live_claim

    root = tmp_path / "claims"
    root.mkdir()
    ClaimStore(root, "owner", now=0.0)._claim("t1")  # claimed at now=0
    # Past the stale window: the only claim is now expired, so no live claim remains.
    assert has_live_claim(root, now=_STALE_AFTER_S + 1) is False


def test_has_live_claim_true_when_unexpired_claim_exists(tmp_path):
    from looptight.claims import has_live_claim

    root = tmp_path / "claims"
    root.mkdir()
    ClaimStore(root, "owner", now=0.0)._claim("t1")  # claimed at now=0
    # Well within the stale window: the claim is still live.
    assert has_live_claim(root, now=1.0) is True


def test_select_returns_none_when_all_tasks_claimed_by_others(tmp_path):
    root = tmp_path / "claims"
    other = ClaimStore(root, "other", now=0.0)
    tasks = [{"id": "t1"}, {"id": "t2"}]
    other.select(tasks)
    other._claim("t2")  # both tasks now held by another owner, unexpired
    assert ClaimStore(root, "me", now=0.0).select(tasks) is None


def test_summary_returns_empty_when_root_absent(tmp_path):
    store = ClaimStore(tmp_path / "missing", "owner", now=0.0)
    assert store.summary() == (None, 0)


def test_claim_rejects_falsy_id_and_read_tolerates_corrupt_file(tmp_path):
    root = tmp_path / "claims"
    root.mkdir()
    store = ClaimStore(root, "owner", now=0.0)
    assert store._claim(None) is False
    assert store._claim("") is False
    bad = root / "bad.json"
    bad.write_text("not json{", encoding="utf-8")
    assert ClaimStore._read(bad) == {}  # corrupt JSON degrades to an empty dict


def test_claim_read_returns_empty_dict_for_valid_non_dict_json(tmp_path):
    # claims.py:145 — the `else {}` branch: valid JSON that is not a dict (e.g. an
    # array) must return {} without raising, distinct from the except (OSError,
    # ValueError) path exercised by the sibling test above with "not json{".
    path = tmp_path / "claim.json"
    path.write_text("[]", encoding="utf-8")
    assert ClaimStore._read(path) == {}


def test_claim_dir_sets_terminal_prompt_env(tmp_path):
    # claim_dir must pass GIT_TERMINAL_PROMPT=0 to git so a headless `looptight next`
    # inside a credential-locked repo can never block on a prompt — the same invariant
    # that test_has_dirty_git_worktree_sets_terminal_prompt_env guards in tasks.py.
    import looptight.claims as claims_mod

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=".git\n", stderr="")

    with patch.object(claims_mod.subprocess, "run", fake_run):
        claim_dir(tmp_path)

    assert "env" in captured, "claim_dir must pass an explicit env to subprocess.run"
    assert captured["env"].get("GIT_TERMINAL_PROMPT") == "0"


def test_claim_dir_absolute_git_common_dir_is_used_directly(tmp_path):
    # claims.py:60 — `git rev-parse --git-common-dir` returns an absolute path in
    # linked worktrees and some submodule setups; the `if not path.is_absolute()`
    # branch is False, so `path` is used as-is without prepending workdir.
    import looptight.claims as claims_mod

    abs_git_dir = tmp_path / "shared_git"
    abs_git_dir.mkdir()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=str(abs_git_dir) + "\n", stderr="")

    with patch.object(claims_mod.subprocess, "run", fake_run):
        result = claim_dir(tmp_path / "worktree")

    assert result == (abs_git_dir / "looptight" / "claims").resolve()


def test_claim_store_select_raises_when_migrated(tmp_path):
    # _fail_closed_if_migrated must raise LegacyClaimsDisabled when the coordinator
    # migration marker exists — the only guard preventing legacy file claims from
    # running silently after a repository migrates to the SQLite coordinator.
    from looptight.claims import MARKER_NAME, LegacyClaimsDisabled

    root = tmp_path / "claims"
    root.mkdir(parents=True)
    # The marker lives one level above the claims dir (i.e. under looptight/).
    (root.parent / MARKER_NAME).write_text("{}", encoding="utf-8")

    store = ClaimStore(root, "owner", now=0.0)

    import pytest

    with pytest.raises(LegacyClaimsDisabled):
        store.select([_task("t1")])

    with pytest.raises(LegacyClaimsDisabled):
        store.summary()
