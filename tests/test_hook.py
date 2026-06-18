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


def test_run_hook_dormant_without_opt_in(tmp_path):
    write_config(Config(verify="pytest -q", hook=False), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail())
    assert output is None  # not armed → never blocks
    assert code == 0


def test_run_hook_blocks_when_armed_and_failing(tmp_path):
    write_config(Config(verify="pytest -q", hook=True), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, code = run_hook(event, verify_fn=lambda c, w: _fail("boom in test_x"))
    assert code == 0
    assert json.loads(output)["decision"] == "block"
    assert "boom in test_x" in json.loads(output)["reason"]


def test_run_hook_allows_when_passing(tmp_path):
    write_config(Config(verify="pytest -q", hook=True), tmp_path)
    event = json.dumps({"cwd": str(tmp_path), "session_id": "s1"})
    output, _ = run_hook(event, verify_fn=lambda c, w: _pass())
    assert output is None


def test_run_hook_counts_continuations_then_gives_up(tmp_path):
    write_config(Config(verify="pytest -q", hook=True, max_iterations=2), tmp_path)
    base = {"cwd": str(tmp_path), "session_id": "s2", "stop_hook_active": True}

    # Fresh user turn (stop_hook_active falsey) → block #1.
    out1, _ = run_hook(json.dumps({**base, "stop_hook_active": False}), verify_fn=lambda c, w: _fail())
    assert json.loads(out1)["decision"] == "block"
    # Continuation → block #2 (cap is 2).
    out2, _ = run_hook(json.dumps(base), verify_fn=lambda c, w: _fail())
    assert json.loads(out2)["decision"] == "block"
    # Continuation → cap reached, allow the stop.
    out3, _ = run_hook(json.dumps(base), verify_fn=lambda c, w: _fail())
    assert out3 is None


def test_run_hook_tolerates_malformed_event():
    output, code = run_hook("not json at all", verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0
