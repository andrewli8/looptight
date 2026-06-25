"""Stop-hook auto-loop: pure policy + the I/O shell."""

from __future__ import annotations

import json

from looptight.config import Config, write_config
from looptight.hook import (
    HookDecision,
    decide,
    read_count,
    run_hook,
    write_count,
)
from looptight.types import VerifyResult


def _fail(output: str = "1 failing test") -> VerifyResult:
    return VerifyResult(passed=False, exit_code=1, output=output)


def _pass() -> VerifyResult:
    return VerifyResult(passed=True, exit_code=0)


def test_decide_blocks_on_failure_under_cap():
    decision, count = decide(_fail(), prior_blocks=0, max_iterations=6)
    assert decision.block is True
    assert "1 failing test" in decision.reason
    assert count == 1


def test_decide_allows_on_pass_and_resets():
    decision, count = decide(_pass(), prior_blocks=3, max_iterations=6)
    assert decision.block is False
    assert count == 0


def test_decide_gives_up_at_cap():
    decision, count = decide(_fail(), prior_blocks=6, max_iterations=6)
    assert decision.block is False  # cap reached, let it stop
    assert count == 0


def test_decision_to_stdout_shapes_claude_json():
    payload = HookDecision(block=True, reason="fix it").to_stdout()
    assert json.loads(payload) == {"decision": "block", "reason": "fix it"}
    assert HookDecision(block=False).to_stdout() is None


def test_count_roundtrip_and_reset(tmp_path):
    path = tmp_path / "count"
    write_count(path, 2)
    assert read_count(path) == 2
    write_count(path, 0)  # reset deletes the file
    assert not path.exists()
    assert read_count(path) == 0


def test_run_hook_blocks_when_verify_is_configured(tmp_path):
    # A repo with a verify command is opted in — no extra hook=true flag needed.
    write_config(Config(verify="pytest -q"), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail("boom in test_x"))
    assert code == 0
    assert json.loads(output)["decision"] == "block"
    assert "boom in test_x" in json.loads(output)["reason"]


def test_run_hook_dormant_without_verify(tmp_path):
    # A repo with no .looptight.toml (and therefore no verify command) stays dormant.
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0


def test_run_hook_allows_when_passing(tmp_path):
    write_config(Config(verify="pytest -q"), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, _ = run_hook(event, verify_fn=lambda c, w: _pass())
    assert output is None


def test_run_hook_carries_count_across_continuations(tmp_path):
    # Three sequential hook invocations with stop_hook_active=True:
    # the second reads the saved count and the third hits the cap.
    write_config(Config(verify="pytest -q"), tmp_path)
    base = {"cwd": str(tmp_path), "session_id": "s2", "stop_hook_active": True}

    # Fresh user turn (stop_hook_active falsey) → block #1.
    out1, _ = run_hook(json.dumps({**base, "stop_hook_active": False}), verify_fn=lambda c, w: _fail())
    assert json.loads(out1)["decision"] == "block"
    # Continuation → block #2 (default cap is 6, so still under).
    out2, _ = run_hook(json.dumps(base), verify_fn=lambda c, w: _fail())
    assert json.loads(out2)["decision"] == "block"


def test_run_hook_tolerates_malformed_event():
    output, code = run_hook("not json at all", verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0


def test_run_hook_tolerates_non_path_cwd():
    event = json.dumps({"cwd": {"unexpected": "object"}})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0


def test_run_hook_tolerates_malformed_config(tmp_path):
    # A broken .looptight.toml must not trap or crash the Stop hook: it behaves
    # like an un-armed repo and lets the stop through (the documented contract).
    (tmp_path / ".looptight.toml").write_text('bad = = toml\n')
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0


def test_run_hook_fails_open_when_continuation_state_cannot_be_saved(tmp_path, monkeypatch):
    write_config(Config(verify="pytest -q"), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})

    def fail_to_save(*args, **kwargs):
        raise PermissionError("read-only temp directory")

    monkeypatch.setattr("looptight.hook.write_count", fail_to_save)

    output, code = run_hook(event, verify_fn=lambda c, w: _fail())

    assert output is None
    assert code == 0
