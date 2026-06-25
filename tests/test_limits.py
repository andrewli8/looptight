"""Provider usage/rate-limit recognition (no token or billing tracking)."""

from __future__ import annotations

from datetime import datetime

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


def test_classify_limit_parses_absolute_reset_time():
    now = datetime(2026, 6, 21, 14, 0, 0)  # 2:00pm
    signal = classify_limit("usage limit reached; resets at 3:00pm", now=now)
    assert signal is not None
    assert signal.retry_after_s == 3600.0


def test_absolute_reset_rolls_to_next_day_when_already_past():
    now = datetime(2026, 6, 21, 16, 0, 0)  # 4:00pm, after a 3pm reset
    signal = classify_limit("rate limit exceeded; try again at 3pm", now=now)
    assert signal is not None
    assert signal.retry_after_s == 23 * 3600.0


def test_absolute_reset_handles_24_hour_clock():
    now = datetime(2026, 6, 21, 14, 30, 0)
    signal = classify_limit("quota exceeded, available again at 15:00", now=now)
    assert signal is not None
    assert signal.retry_after_s == 30 * 60.0


def test_relative_reset_takes_precedence_over_absolute():
    now = datetime(2026, 6, 21, 14, 0, 0)
    signal = classify_limit("rate limit; retry after 30", now=now)
    assert signal is not None
    assert signal.retry_after_s == 30.0


def test_absolute_reset_ignored_without_reset_context():
    # A bare clock time with no reset/again wording must not be treated as a reset.
    now = datetime(2026, 6, 21, 14, 0, 0)
    signal = classify_limit("rate limit hit while polling endpoint at 3pm", now=now)
    assert signal is not None
    assert signal.retry_after_s is None


def test_absolute_reset_ignores_out_of_range_clock_time():
    now = datetime(2026, 6, 21, 14, 0, 0)
    signal = classify_limit("usage limit reached; resets at 13:00pm", now=now)
    assert signal is not None
    assert signal.retry_after_s is None


def test_absolute_reset_handles_midnight_12am():
    # "12:00am" is midnight (hour 0), so from 11pm the next reset is one hour out.
    now = datetime(2026, 6, 21, 23, 0, 0)
    signal = classify_limit("usage limit reached; resets at 12:00am", now=now)
    assert signal is not None
    assert signal.retry_after_s == pytest.approx(3600.0)


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
