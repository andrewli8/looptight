"""Stop-hook auto-loop: pure policy + the I/O shell."""

from __future__ import annotations

import json

from looptight.config import Config, write_config
from looptight.hook import (
    HookDecision,
    continuation_reason,
    decide,
    read_count,
    run_hook,
    write_count,
)
from looptight.types import VerifyResult


def test_continuation_reason_marks_truncated_verify_output():
    # A huge verify output is fed back to the agent on every continuation; it is
    # truncated to a tail, but must be MARKED (like the run loop's continuation
    # context), or the agent mistakes a partial tail for the whole verify output.
    long_reason = continuation_reason(VerifyResult(passed=False, exit_code=1, output="E" * 9000))
    assert "truncated" in long_reason, "truncation of verify output was not marked"
    assert len(long_reason) < 4000, "continuation reason is not bounded"
    # A short output is included whole, with no spurious marker.
    short_reason = continuation_reason(VerifyResult(passed=False, exit_code=1, output="one failure"))
    assert "truncated" not in short_reason
    assert "one failure" in short_reason


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


def test_run_hook_carries_count_across_continuations(tmp_path, monkeypatch):
    # Three sequential hook invocations with max_iterations=2:
    # first two block, the third reads the persisted count=2 and allows.
    import looptight.hook as _hook
    monkeypatch.setattr(_hook, "_config_for", lambda cwd: Config(verify="pytest -q", max_iterations=2))
    base = {"cwd": str(tmp_path), "session_id": "s2", "stop_hook_active": True}

    # Fresh user turn (stop_hook_active falsey) → block #1, saves count=1.
    out1, _ = run_hook(json.dumps({**base, "stop_hook_active": False}), verify_fn=lambda c, w: _fail())
    assert json.loads(out1)["decision"] == "block"
    # First continuation: reads count=1, blocks, saves count=2.
    out2, _ = run_hook(json.dumps(base), verify_fn=lambda c, w: _fail())
    assert json.loads(out2)["decision"] == "block"
    # Second continuation: reads count=2, cap reached (prior_blocks >= max_iterations), allows.
    out3, _ = run_hook(json.dumps(base), verify_fn=lambda c, w: _fail())
    assert out3 is None


def test_run_hook_tolerates_malformed_event():
    output, code = run_hook("not json at all", verify_fn=lambda c, w: _fail())
    assert output is None
    assert code == 0


def test_run_hook_tolerates_valid_json_non_dict_event():
    # Valid JSON that is not a dict (e.g. a list) must be treated like a malformed
    # event: allow the stop (None, 0) without raising — the not-a-dict guard at hook.py:120.
    output, code = run_hook("[]", verify_fn=lambda c, w: _fail())
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
