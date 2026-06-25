"""The verify oracle (B3)."""

from __future__ import annotations

import os
import time

import pytest

from looptight.types import VerifyResult
from looptight.verify import (
    _MAX_OUTPUT_CHARS,
    _as_text,
    _stop_process_tree,
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


def test_timeout_stops_delayed_child_process_work(tmp_path, monkeypatch):
    if os.name != "posix":
        calls = []

        class Process:
            pid = 123
            killed = False

            def kill(self):
                self.killed = True

        process = Process()

        def taskkill(command, **kwargs):
            calls.append(command)
            return type("Result", (), {"returncode": 0})()

        monkeypatch.setattr("looptight.verify.subprocess.run", taskkill)
        _stop_process_tree(process)  # type: ignore[arg-type]
        assert calls == [["taskkill", "/F", "/T", "/PID", "123"]]
        assert not process.killed
        return

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
