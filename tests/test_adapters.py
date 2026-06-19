"""Adapter registry + the delegate/supply split (F1)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from looptight.adapters import available_adapter_names, get_adapter
from looptight.adapters.claude import ClaudeAdapter, _build_prompt, _parse_result


def test_registry_lists_three_agents():
    assert set(available_adapter_names()) == {"claude", "codex", "opencode"}


def test_native_loop_capability():
    # Claude ships /goal (drivable headlessly); codex/opencode are supply-only.
    assert get_adapter("claude").supports_native_loop is True
    assert get_adapter("codex").supports_native_loop is False
    assert get_adapter("opencode").supports_native_loop is False


def test_memory_files_match_each_agent():
    assert get_adapter("claude").memory_filename == "CLAUDE.md"
    assert get_adapter("codex").memory_filename == "AGENTS.md"
    assert get_adapter("opencode").memory_filename == "AGENTS.md"


def test_unknown_agent_raises():
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_claude_prompt_includes_goal_and_context():
    prompt = _build_prompt("fix the parser", "verify says: 2 failing")
    assert "fix the parser" in prompt
    assert "2 failing" in prompt


def test_claude_parses_cost_from_json():
    text, cost = _parse_result('{"result": "done", "total_cost_usd": 0.12}')
    assert text == "done"
    assert cost == 0.12


def test_claude_parse_tolerates_non_json():
    text, cost = _parse_result("plain text, no json")
    assert "plain text" in text
    assert cost == 0.0


def test_claude_parse_tolerates_non_object_json(tmp_path):
    # Valid JSON that isn't an object (array/scalar) must degrade to text, not
    # crash on a missing .get — the CLI output is untrusted external data.
    text, cost = _parse_result("[1, 2, 3]")
    assert text == "[1, 2, 3]"
    assert cost == 0.0


def test_claude_parse_tolerates_non_numeric_cost():
    text, cost = _parse_result('{"result": "done", "total_cost_usd": "lots"}')
    assert text == "done"
    assert cost == 0.0


def test_claude_parse_matches_recorded_cli_output():
    # Contract test against a recorded `claude -p --output-format json` blob.
    # If Claude Code's JSON schema drifts, this fails loudly instead of us
    # silently reading $0.00. Refresh the fixture when the CLI changes.
    fixture = Path(__file__).parent / "fixtures" / "claude_result.json"
    text, cost = _parse_result(fixture.read_text())
    assert "paginate()" in text
    assert cost == 0.0142


def test_claude_builds_goal_prompt_for_native_loop(monkeypatch):
    # drive_native_loop should phrase the goal as a /goal condition over verify.
    captured = {}

    def fake_invoke(self, prompt, workdir, model):
        captured["prompt"] = prompt
        import subprocess

        return subprocess.CompletedProcess(args=[], returncode=0, stdout='{"result": "ok", "total_cost_usd": 0.0}', stderr="")

    monkeypatch.setattr(ClaudeAdapter, "_invoke", fake_invoke)
    ClaudeAdapter().drive_native_loop("fix tests", "pytest -q", 4, 1.0, Path("."))
    assert "/goal" in captured["prompt"]
    assert "pytest -q" in captured["prompt"]


def test_supply_only_adapters_refuse_native_loop():
    # codex/opencode don't fake a native loop they can't drive.
    for name in ("codex", "opencode"):
        with pytest.raises(NotImplementedError):
            get_adapter(name).drive_native_loop("g", "v", 3, 1.0, Path("."))


def test_codex_and_opencode_build_prompts_with_goal_and_context():
    from looptight.adapters.codex import _build_prompt as codex_prompt
    from looptight.adapters.opencode import _build_prompt as opencode_prompt

    for builder in (codex_prompt, opencode_prompt):
        prompt = builder("fix the parser", "2 failing")
        assert "fix the parser" in prompt
        assert "2 failing" in prompt


@pytest.mark.parametrize("name", available_adapter_names())
def test_agent_launch_failure_is_returned_as_iteration_error(name, monkeypatch, tmp_path):
    def fail_to_launch(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(subprocess, "run", fail_to_launch)

    result = get_adapter(name).run_iteration("fix it", "", tmp_path)

    assert result.ok is False
    assert result.error == f"{name} exited 127"
    assert "permission denied" in result.transcript


def test_codex_reflect_returns_none_on_nonzero_exit(monkeypatch, tmp_path):
    import subprocess

    from looptight.adapters.codex import CodexAdapter

    def fake_exec(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")

    monkeypatch.setattr(CodexAdapter, "_exec", lambda self, p, w: fake_exec())
    assert CodexAdapter().reflect("some prompt", tmp_path) is None


def test_codex_reflect_returns_stripped_text_on_success(monkeypatch, tmp_path):
    import subprocess

    from looptight.adapters.codex import CodexAdapter

    def fake_exec(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="  Pin the timeout.  ", stderr="")

    monkeypatch.setattr(CodexAdapter, "_exec", lambda self, p, w: fake_exec())
    assert CodexAdapter().reflect("some prompt", tmp_path) == "Pin the timeout."


def test_opencode_reflect_returns_none_on_nonzero_exit(monkeypatch, tmp_path):
    import subprocess

    from looptight.adapters.opencode import OpencodeAdapter

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")

    monkeypatch.setattr(OpencodeAdapter, "_run", lambda self, p, w: fake_run())
    assert OpencodeAdapter().reflect("some prompt", tmp_path) is None
