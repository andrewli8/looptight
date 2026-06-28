"""Adapter registry + the delegate/supply split (F1)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from looptight.adapters import available_adapter_names, get_adapter
from looptight.adapters.base import run_command
from looptight.adapters.claude import ClaudeAdapter, _build_prompt, _parse_result
from looptight.limits import is_limit_error


def test_registry_lists_three_agents():
    assert set(available_adapter_names()) == {"claude", "codex", "opencode"}


def test_run_command_tolerates_non_utf8_output(tmp_path):
    # Agent CLI output is untrusted bytes; non-UTF-8 must not crash an iteration.
    proc = run_command(["sh", "-c", r"printf '\377\376'; exit 2"], tmp_path)
    assert proc.returncode == 2


def test_provider_adapter_passes_worker_timeout_to_command(monkeypatch, tmp_path):
    captured = {}

    def fake_run_command(cmd, workdir, *, timeout_s):
        captured["timeout_s"] = timeout_s
        return subprocess.CompletedProcess(cmd, 124, "", "provider timed out after 3s")

    monkeypatch.setattr("looptight.adapters.codex.run_command", fake_run_command)
    adapter = get_adapter("codex")
    adapter.worker_timeout_s = 3

    result = adapter.run_iteration("fix it", "", tmp_path)

    assert captured["timeout_s"] == 3
    assert result.error == "provider timed out after 3s"


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


def test_claude_parses_result_from_json():
    assert _parse_result('{"result": "done", "total_cost_usd": 0.12}') == "done"


def test_claude_parse_tolerates_non_json():
    assert "plain text" in _parse_result("plain text, no json")


def test_claude_parse_tolerates_non_object_json(tmp_path):
    # Valid JSON that isn't an object (array/scalar) must degrade to text, not
    # crash on a missing .get — the CLI output is untrusted external data.
    assert _parse_result("[1, 2, 3]") == "[1, 2, 3]"


def test_claude_parse_matches_recorded_cli_output():
    # Contract test against a recorded `claude -p --output-format json` blob.
    # If Claude Code's JSON schema drifts, this fails loudly instead of us
    # silently reading $0.00. Refresh the fixture when the CLI changes.
    fixture = Path(__file__).parent / "fixtures" / "claude_result.json"
    assert "paginate()" in _parse_result(fixture.read_text())


def test_claude_builds_goal_prompt_for_native_loop(monkeypatch):
    # drive_native_loop should phrase the goal as a /goal condition over verify.
    captured = {}

    def fake_invoke(self, prompt, workdir, model):
        captured["prompt"] = prompt
        import subprocess

        return subprocess.CompletedProcess(args=[], returncode=0, stdout='{"result": "ok", "total_cost_usd": 0.0}', stderr="")

    monkeypatch.setattr(ClaudeAdapter, "_invoke", fake_invoke)
    ClaudeAdapter().drive_native_loop("fix tests", "pytest -q", 4, Path("."))
    assert "/goal" in captured["prompt"]
    assert "pytest -q" in captured["prompt"]


def test_claude_native_loop_threads_the_configured_model(monkeypatch):
    # --model must reach the native /goal loop too, not only the supply path.
    # Previously drive_native_loop hardcoded model=None, silently discarding the
    # user's requested model in --native mode.
    captured = {}

    def fake_invoke(self, prompt, workdir, model):
        captured["model"] = model
        import subprocess

        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"result": "ok"}', stderr=""
        )

    monkeypatch.setattr(ClaudeAdapter, "_invoke", fake_invoke)
    ClaudeAdapter().drive_native_loop("fix tests", "pytest -q", 4, Path("."), model="opus")
    assert captured["model"] == "opus"


def test_claude_native_loop_surfaces_usage_limit_with_stable_marker(monkeypatch):
    # A usage limit during the native /goal loop must carry the stable marker so
    # the delegate loop's --resume-on-limit can wait it out and retry — the same
    # contract the supply path provides via failure_iteration. Without it the
    # only native-capable adapter could never trigger the documented resume.
    def fake_invoke(self, prompt, workdir, model):
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Error: usage limit reached; retry after 60"
        )

    monkeypatch.setattr(ClaudeAdapter, "_invoke", fake_invoke)
    result = ClaudeAdapter().drive_native_loop("fix tests", "pytest -q", 4, Path("."))

    assert result.ok is False
    assert result.error == "provider rate limit reached; retry after 60s"


def test_claude_native_loop_plain_failure_is_not_a_limit(monkeypatch):
    # An ordinary non-zero native exit must NOT be tagged as a limit, so the
    # resume wrapper does not spin on a genuine failure.
    def fake_invoke(self, prompt, workdir, model):
        return subprocess.CompletedProcess(
            args=[], returncode=2, stdout="", stderr="AssertionError: boom"
        )

    monkeypatch.setattr(ClaudeAdapter, "_invoke", fake_invoke)
    result = ClaudeAdapter().drive_native_loop("fix tests", "pytest -q", 4, Path("."))

    assert result.ok is False
    assert not is_limit_error(result.error)
    assert "AssertionError: boom" in result.transcript


def test_supply_only_adapters_refuse_native_loop():
    # codex/opencode don't fake a native loop they can't drive.
    for name in ("codex", "opencode"):
        with pytest.raises(NotImplementedError):
            get_adapter(name).drive_native_loop("g", "v", 3, Path("."))


def test_codex_and_opencode_build_prompts_with_goal_and_context():
    from looptight.adapters.codex import _build_prompt as codex_prompt
    from looptight.adapters.opencode import _build_prompt as opencode_prompt

    for builder in (codex_prompt, opencode_prompt):
        prompt = builder("fix the parser", "2 failing")
        assert "fix the parser" in prompt
        assert "2 failing" in prompt


@pytest.mark.parametrize("name", available_adapter_names())
def test_provider_usage_limit_is_surfaced_with_stable_marker(name, monkeypatch, tmp_path):
    # A usage/rate-limit exit must be distinguishable from a plain failure so the
    # continuous swarm can wait it out instead of stopping.
    def fake_run_command(cmd, workdir, *, timeout_s=None):
        return subprocess.CompletedProcess(cmd, 1, "", "Error: usage limit reached; retry after 60")

    monkeypatch.setattr(f"looptight.adapters.{name}.run_command", fake_run_command)

    result = get_adapter(name).run_iteration("fix it", "", tmp_path)

    assert result.ok is False
    assert result.error == "provider rate limit reached; retry after 60s"


@pytest.mark.parametrize("name", available_adapter_names())
def test_plain_nonzero_exit_is_not_mistaken_for_a_limit(name, monkeypatch, tmp_path):
    def fake_run_command(cmd, workdir, *, timeout_s=None):
        return subprocess.CompletedProcess(cmd, 1, "", "AssertionError: boom")

    monkeypatch.setattr(f"looptight.adapters.{name}.run_command", fake_run_command)

    result = get_adapter(name).run_iteration("fix it", "", tmp_path)

    assert result.ok is False
    assert result.error == f"{name} exited 1"


@pytest.mark.parametrize("name", available_adapter_names())
def test_agent_launch_failure_is_returned_as_iteration_error(name, monkeypatch, tmp_path):
    def fail_to_launch(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(subprocess, "run", fail_to_launch)

    result = get_adapter(name).run_iteration("fix it", "", tmp_path)

    assert result.ok is False
    assert result.error == f"{name} exited 127"
    assert "permission denied" in result.transcript
