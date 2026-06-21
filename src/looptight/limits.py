"""Recognize provider-reported usage/rate limits from agent CLI output.

looptight never tracks tokens, credits, or billing — ``docs/SPEC.md`` makes
provider-native usage limits authoritative. This module only *recognizes* a limit
the provider already reported in its own stdout/stderr, plus any relative reset
interval it named, so the continuous swarm can wait the limit out and resume
instead of treating it as a terminal failure. It is pure (stdlib ``re`` only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

#: Stable marker prefix carried on an ``IterationResult``/worker error when a
#: failed provider invocation was a usage/rate limit. The continuous swarm keys
#: its back-off on this prefix the same way it keys timeouts on a fixed phrase.
RATE_LIMIT_ERROR = "provider rate limit reached"

#: Defaults for waiting out a usage limit, shared by the swarm and the single
#: headless loop. Off unless the caller opts in.
DEFAULT_LIMIT_BACKOFF = 30.0
DEFAULT_LIMIT_MAX_WAIT = 3600.0

# Phrases coding-agent CLIs emit when the account is rate-limited or out of usage,
# matched case-insensitively. Anchored to error phrasing; this only runs on a
# failed (non-zero) invocation, so ordinary code mentioning "rate limit" is safe.
_LIMIT_PATTERNS = (
    r"usage limit",
    r"rate[ -]?limit",
    r"\b429\b",
    r"too many requests",
    r"quota",
    r"you (?:have )?exceeded",
    r"overloaded",
    r"insufficient (?:quota|credit)",
)

_UNIT_SECONDS = {
    "": 1.0,
    "s": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "mins": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}

# "retry after 30", "retry-after: 90s", "try again in 5 minutes".
_RELATIVE_RE = re.compile(
    r"(?:retry[ -]?after|try again in)[:\s]+(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|minutes?|mins?|hours?|hrs?|[smh])?\b",
    re.IGNORECASE,
)

# Absolute wall-clock reset ("resets at 3:00pm", "available again at 15:00"),
# used only when no relative interval is named and the text actually talks about
# a reset — so a bare "at 3pm" elsewhere is not mistaken for one.
_AT_TIME_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?", re.IGNORECASE)
_RESET_CONTEXT_RE = re.compile(r"reset|again|available|back online", re.IGNORECASE)

_ERROR_RETRY_RE = re.compile(r"retry after (\d+)s")


@dataclass(frozen=True)
class LimitSignal:
    """A recognized provider limit, with the named reset interval if any."""

    retry_after_s: float | None = None


def _parse_relative_reset(text: str) -> float | None:
    match = _RELATIVE_RE.search(text)
    if not match:
        return None
    seconds = float(match.group(1)) * _UNIT_SECONDS.get((match.group(2) or "").lower(), 1.0)
    return seconds if seconds > 0 else None


def _parse_absolute_reset(text: str, now: datetime | None) -> float | None:
    if not _RESET_CONTEXT_RE.search(text):
        return None
    match = _AT_TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower().replace(".", "")
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    current = now or datetime.now()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


def _parse_reset(text: str, now: datetime | None) -> float | None:
    relative = _parse_relative_reset(text)
    if relative is not None:
        return relative
    return _parse_absolute_reset(text, now)


def classify_limit(text: str, now: datetime | None = None) -> LimitSignal | None:
    """Return a ``LimitSignal`` if ``text`` reports a usage/rate limit, else None.

    ``now`` (injected for testing; defaults to the current time) anchors any
    absolute wall-clock reset the provider named.
    """
    if not text:
        return None
    lowered = text.lower()
    if not any(re.search(pattern, lowered) for pattern in _LIMIT_PATTERNS):
        return None
    return LimitSignal(retry_after_s=_parse_reset(text, now))


def format_limit_error(signal: LimitSignal) -> str:
    """Encode a limit signal as a worker/iteration error string."""
    if signal.retry_after_s:
        return f"{RATE_LIMIT_ERROR}; retry after {int(signal.retry_after_s)}s"
    return RATE_LIMIT_ERROR


def is_limit_error(error: str | None) -> bool:
    """True if ``error`` was produced by :func:`format_limit_error`."""
    return bool(error) and error.startswith(RATE_LIMIT_ERROR)


def retry_after_from_error(error: str | None) -> float | None:
    """Recover the named reset interval encoded by :func:`format_limit_error`."""
    if not error:
        return None
    match = _ERROR_RETRY_RE.search(error)
    return float(match.group(1)) if match else None


def limit_wait(retry_after: float | None, attempt: int, base: float, cap: float) -> float:
    """Seconds to wait before resuming after a usage limit.

    Prefer the reset interval the provider named; otherwise back off exponentially
    from ``base``. Always bounded by ``cap`` so a single sleep can never run away —
    a longer real reset is handled by re-polling, not one unbounded wait.
    """
    wait = retry_after if retry_after and retry_after > 0 else base * (2 ** (attempt - 1))
    return min(wait, cap)
