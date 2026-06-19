"""The verify oracle (B3)."""

from __future__ import annotations

import subprocess

from looptight.verify import parse_score, run_verify


def test_passing_command(tmp_path):
    result = run_verify("exit 0", tmp_path)
    assert result.passed
    assert result.exit_code == 0


def test_failing_command(tmp_path):
    result = run_verify("exit 1", tmp_path)
    assert not result.passed
    assert result.exit_code == 1


def test_captures_output(tmp_path):
    result = run_verify("echo hello from verify", tmp_path)
    assert "hello from verify" in result.output


def test_parses_score_line():
    assert parse_score("running...\nSCORE: 0.83\n") == 0.83
    assert parse_score("SCORE: 1\nSCORE: 2\n") == 2.0  # last wins
    assert parse_score("no score here") is None


def test_score_surfaced_in_result(tmp_path):
    result = run_verify("echo 'SCORE: 0.5'", tmp_path)
    assert result.score == 0.5


def test_score_parsed_from_full_output_even_when_truncated(tmp_path):
    # A SCORE line buried in the middle of large output must still be read: the
    # score comes from the full output, not the head+tail truncated copy.
    big = "x" * 9000
    result = run_verify(f"echo {big}; echo 'SCORE: 0.77'; echo {big}", tmp_path)
    assert result.score == 0.77
    assert "[truncated]" in result.output  # output itself is still bounded


def test_missing_command_is_failure_not_crash(tmp_path):
    result = run_verify("this-binary-does-not-exist-xyz", tmp_path)
    assert not result.passed  # shell reports 127, captured as a failure


def test_timeout_is_failure_not_crash(tmp_path, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep 999", timeout=0.001)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = run_verify("sleep 999", tmp_path, timeout_s=0.001)
    assert not result.passed
    assert result.exit_code == 124
    assert "timed out" in result.output


def test_timeout_preserves_partial_verify_output(tmp_path, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="slow verify",
            timeout=1,
            output=b"test_widget.py::test_save FAILED\n",
            stderr=b"AssertionError: expected saved record\n",
        )

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    result = run_verify("slow verify", tmp_path, timeout_s=1)

    assert "test_widget.py::test_save FAILED" in result.output
    assert "AssertionError: expected saved record" in result.output
    assert "verify timed out after 1s" in result.output
