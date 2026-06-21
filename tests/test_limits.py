"""Provider usage/rate-limit recognition (no token or billing tracking)."""

from __future__ import annotations

import pytest

from looptight.limits import (
    RATE_LIMIT_ERROR,
    LimitSignal,
    classify_limit,
    format_limit_error,
    is_limit_error,
    retry_after_from_error,
)


@pytest.mark.parametrize(
    "text",
    [
        "Claude usage limit reached. Try again later.",
        "Error: rate limit exceeded",
        "you are being rate-limited",
        "HTTP 429 Too Many Requests",
        "quota exceeded for this account",
        "You have exceeded your current quota",
        "the model is overloaded right now",
        "insufficient credit to continue",
    ],
)
def test_classify_limit_matches_provider_idioms(text):
    assert classify_limit(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "claude exited 1",
        "AssertionError: expected 2 got 3",
        "ModuleNotFoundError: no module named 'foo'",
        "could not launch codex: No such file or directory",
    ],
)
def test_classify_limit_ignores_ordinary_failures(text):
    assert classify_limit(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("rate limit; retry after 30", 30.0),
        ("usage limit reached. retry-after: 90s", 90.0),
        ("429: try again in 5 minutes", 300.0),
        ("quota exceeded, try again in 2 hours", 7200.0),
        ("rate limit reached, retry after 45 seconds", 45.0),
    ],
)
def test_classify_limit_parses_relative_reset(text, expected):
    signal = classify_limit(text)
    assert signal is not None
    assert signal.retry_after_s == expected


def test_classify_limit_without_reset_has_no_retry_after():
    signal = classify_limit("usage limit reached")
    assert signal == LimitSignal(retry_after_s=None)


def test_format_and_parse_round_trip():
    error = format_limit_error(LimitSignal(retry_after_s=120.0))
    assert error.startswith(RATE_LIMIT_ERROR)
    assert is_limit_error(error)
    assert retry_after_from_error(error) == 120.0


def test_format_limit_error_without_reset_is_bare_marker():
    error = format_limit_error(LimitSignal(retry_after_s=None))
    assert error == RATE_LIMIT_ERROR
    assert is_limit_error(error)
    assert retry_after_from_error(error) is None


def test_is_limit_error_rejects_other_failures():
    assert not is_limit_error(None)
    assert not is_limit_error("codex exited 1")
    assert not is_limit_error("provider timed out after 30s")
