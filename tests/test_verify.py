"""The verify oracle (B3)."""

from __future__ import annotations

import os
import time

import pytest

from looptight.types import VerifyResult
from looptight.verify import (
    _MAX_OUTPUT_CHARS,
    _as_text,
    _timeout_output,
    _truncate,
    parse_score,
    run_verify,
)


def test_passing_command(tmp_path):
    result = run_verify("exit 0", tmp_path)
    assert result.passed
    assert result.exit_code == 0


def test_failing_command(tmp_path):
    result = run_verify("exit 1", tmp_path)
    assert not result.passed
    assert result.exit_code == 1


def test_blank_command_never_passes(tmp_path):
    # A whitespace-only command runs a no-op shell that exits 0; verify is the only commit
    # authority, so it must refuse to treat that as a pass.
    for blank in ("", "   ", "\t\n"):
        result = run_verify(blank, tmp_path)
        assert not result.passed and result.error == "blank_verify"
        assert result.exit_code == 2


def test_verify_result_rejects_contradictory_verdict():
    with pytest.raises(ValueError, match="exit code zero"):
        VerifyResult(passed=True, exit_code=1)

    with pytest.raises(ValueError, match="execution error"):
        VerifyResult(passed=True, exit_code=0, error="launch_error")


def test_captures_output(tmp_path):
    result = run_verify("echo hello from verify", tmp_path)
    assert "hello from verify" in result.output


def test_parses_score_line():
    assert parse_score("running...\nSCORE: 0.83\n") == 0.83
    assert parse_score("SCORE: 1\nSCORE: 2\n") == 2.0  # last wins
    assert parse_score("no score here") is None
    assert parse_score(None) is None  # missing output is treated as empty


def test_score_surfaced_in_result(tmp_path):
    result = run_verify("echo 'SCORE: 0.5'", tmp_path)
    assert result.score == 0.5


def test_run_verify_tolerates_non_utf8_output(tmp_path):
    # The verify oracle must never crash on a command's raw bytes; invalid UTF-8
    # is decoded leniently rather than raising UnicodeDecodeError.
    result = run_verify(r"printf '\377\376'; exit 3", tmp_path)
    assert result.exit_code == 3
    assert result.status == "fail"
    assert not result.passed


def test_score_parsed_from_full_output_even_when_truncated(tmp_path):
    # A SCORE line buried in the middle of large output must still be read: the
    # score comes from the full output, not the head+tail truncated copy.
    big = "x" * 9000
    result = run_verify(f"echo {big}; echo 'SCORE: 0.77'; echo {big}", tmp_path)
    assert result.score == 0.77
    assert "[truncated]" in result.output  # output itself is still bounded


def test_missing_command_is_launch_error_not_test_failure(tmp_path):
    result = run_verify("this-binary-does-not-exist-xyz", tmp_path)
    assert not result.passed
    assert result.exit_code == 127
    assert result.status == "error"
    assert result.error == "launch_error"


@pytest.mark.skipif(os.name != "posix", reason="exit 126 is a POSIX shell concept")
def test_non_executable_script_is_launch_error_not_test_failure(tmp_path):
    script = tmp_path / "verify.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    # intentionally no chmod +x — the shell returns 126 for non-executable files
    result = run_verify(str(script), tmp_path)
    assert not result.passed
    assert result.exit_code == 126
    assert result.status == "error"
    assert result.error == "launch_error"


def test_ordinary_nonzero_exit_remains_test_failure(tmp_path):
    result = run_verify("exit 1", tmp_path)
    assert result.status == "fail"
    assert result.error is None


def test_timeout_is_failure_not_crash(tmp_path):
    result = run_verify("sleep 1", tmp_path, timeout_s=0.01)
    assert not result.passed
    assert result.exit_code == 124
    assert "timed out" in result.output


def test_timeout_preserves_partial_verify_output(tmp_path):
    command = (
        "printf 'test_widget.py::test_save FAILED\\n'; "
        "printf 'AssertionError: expected saved record\\n' >&2; sleep 1"
    )
    result = run_verify(command, tmp_path, timeout_s=0.05)

    assert "test_widget.py::test_save FAILED" in result.output
    assert "AssertionError: expected saved record" in result.output
    assert "verify timed out after 0.05s" in result.output
    assert result.status == "timeout"


def test_run_verify_sets_git_terminal_prompt(tmp_path, monkeypatch):
    """Popen must receive GIT_TERMINAL_PROMPT=0 so headless git never blocks on a credential prompt."""
    import subprocess as _subprocess
    from unittest.mock import patch

    captured_env = {}

    original_popen = _subprocess.Popen

    def fake_popen(*args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return original_popen(*args, **kwargs)

    with patch("looptight.verify.subprocess.Popen", side_effect=fake_popen):
        run_verify("exit 0", tmp_path)

    assert captured_env.get("GIT_TERMINAL_PROMPT") == "0"


@pytest.mark.skipif(os.name != "posix", reason="posix process-group orphan test")
def test_timeout_stops_delayed_child_process_work(tmp_path):
    # The Windows taskkill branch is covered by test_proctree; here we prove the
    # posix process-group teardown leaves no orphan that touches the marker.
    marker = tmp_path / "orphaned"
    result = run_verify(
        f"(sleep 0.2; touch {marker}) & wait",
        tmp_path,
        timeout_s=0.02,
    )

    assert result.status == "timeout"
    time.sleep(0.35)
    assert not marker.exists()


def test_truncate_respects_max_output_bound():
    # The head+tail separator must count against the budget: the truncated
    # output stays within the documented cap, never overshooting it.
    truncated = _truncate("x" * (5 * _MAX_OUTPUT_CHARS))
    assert "[truncated]" in truncated
    assert len(truncated) <= _MAX_OUTPUT_CHARS


def test_truncate_leaves_short_text_unchanged():
    short = "ok\n"
    assert _truncate(short) == short


def test_as_text_decodes_bytes():
    assert _as_text(b"hello") == "hello"


def test_as_text_returns_empty_string_for_none():
    assert _as_text(None) == ""


def test_as_text_passes_str_through():
    assert _as_text("already str") == "already str"


def test_timeout_output_with_partial_output():
    result = _timeout_output("partial output", "pytest -q", 5.0)
    assert "partial output" in result
    assert "timed out after 5s" in result
    assert "pytest -q" in result


def test_timeout_output_empty_partial_has_no_leading_separator():
    result = _timeout_output("", "pytest -q", 10.0)
    assert result.startswith("verify timed out")


def test_timeout_output_partial_ending_with_newline_has_no_double_newline():
    # verify.py:52 — the separator is "" when partial already ends with "\n",
    # so no spurious blank line appears before the timeout message.
    result = _timeout_output("partial\n", "pytest -q", 5.0)
    assert "\n\nverify" not in result  # no double blank line
    assert "partial\nverify" in result  # partial and message are adjacent


def test_context_output_passthrough_and_truncation_marker():
    # Short output — returned whole, no truncation marker added.
    short = VerifyResult(passed=False, exit_code=1, output="one failure\n")
    assert short.context_output(100) == "one failure\n"
    assert "truncated" not in short.context_output(100)

    # Long output — the dropped prefix is named; only the tail survives.
    big = "A" * 30 + "B" * 10
    result = VerifyResult(passed=False, exit_code=1, output=big)
    out = result.context_output(10)
    dropped = len(big) - 10
    assert f"[...{dropped} earlier characters truncated...]" in out
    assert out.endswith("B" * 10)
    assert "A" not in out  # prefix is gone

    # Output exactly at the limit — passthrough (no off-by-one).
    exact = "Z" * 10
    assert VerifyResult(passed=True, exit_code=0, output=exact).context_output(10) == exact


def test_short_includes_score_when_present():
    assert VerifyResult(passed=True, exit_code=0, score=0.85).short() == "PASS (score 0.85)"
    assert VerifyResult(passed=False, exit_code=1, score=0.0).short() == "FAIL (score 0)"


def test_short_distinguishes_timeout_and_error_from_a_plain_fail():
    # short() drives the verify headline; it must not mislabel an execution timeout/error as a
    # test FAIL (which would mislead the user — and is why a redundant status echo is unneeded).
    assert VerifyResult(passed=False, exit_code=2, error="timeout").short() == "TIMEOUT"
    assert VerifyResult(passed=False, exit_code=1, error="boom").short() == "ERROR"
    assert VerifyResult(passed=False, exit_code=1).short() == "FAIL"  # plain fail unchanged
    assert VerifyResult(passed=True, exit_code=0).short() == "PASS"
    # the score suffix is preserved on the real status
    assert VerifyResult(passed=False, exit_code=2, error="timeout", score=0.5).short() == "TIMEOUT (score 0.5)"


def test_popen_oserror_is_launch_error(tmp_path, monkeypatch):
    # The except OSError branch at verify.py:90 catches OS-level launch failures
    # (e.g. PermissionError) that the shell-127 path never exercises.  Injecting
    # OSError directly into Popen proves the branch returns error="launch_error"
    # with exit_code 127 instead of propagating the exception.
    import looptight.verify as verify_mod

    monkeypatch.setattr(
        verify_mod.subprocess,
        "Popen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("permission denied")),
    )
    result = run_verify("pytest -q", tmp_path)
    assert result.error == "launch_error"
    assert result.exit_code == 127
    assert not result.passed
