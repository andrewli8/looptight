"""Readable, gif-able run summary (E1, E2).

The artifact people screenshot. One backend-neutral renderer for both the
supplied loop and a delegated native loop. Plain text by default; the same lines
render with colour when a rich Console is passed in.
"""

from __future__ import annotations

from .types import RunResult, StopReason

_REASON_TEXT = {
    StopReason.SUCCESS: "done",
    StopReason.ITERATION_CAP: "stopped: hit iteration cap",
    StopReason.NO_PROGRESS: "stopped early: no measurable progress (cut losses)",
    StopReason.ESCALATED: "stopped: stuck with no progress, worth a human look",
    StopReason.NO_VERIFY: "stopped: no verify command (no verify, no loop)",
    StopReason.AGENT_UNAVAILABLE: "stopped: no coding agent found on PATH",
    StopReason.ERROR: "stopped: error",
}


def header(result: RunResult) -> str:
    verb = "driving native loop" if result.mode == "delegate" else "supplying loop"
    return f"looptight · agent: {result.agent} ({verb})"


def _tail(result: RunResult) -> str:
    """The final status fragment, surfacing the error text on an ERROR stop."""
    text = _REASON_TEXT.get(result.stop_reason, result.stop_reason.value)
    if result.stop_reason is StopReason.ERROR and result.error:
        return f"{text}: {result.error}"
    return text


def render(result: RunResult) -> str:
    """Full plain-text summary."""
    lines = [header(result), ""]
    for record in result.iterations:
        lines.append(record.line())

    mark = "✓" if result.passed else "✗"
    tail = _tail(result)
    lines.append("")
    lines.append(f"{mark} {tail} · {result.iteration_count} iteration(s)")
    if result.diffstat:
        lines += ["", "changes:", result.diffstat]
    return "\n".join(lines)


def render_rich(result: RunResult, console) -> None:
    """Print the summary to a rich Console with green/red emphasis (E2)."""
    console.print(header(result), style="bold")
    console.print()
    for record in result.iterations:
        style = "green" if record.verify.passed else "red"
        console.print(f"iteration {record.number} → verify: ", end="")
        console.print(record.verify.short(), style=f"bold {style}", end="")
        console.print()

    passed = result.passed
    mark = "✓" if passed else "✗"
    tail = _tail(result)
    console.print()
    console.print(
        f"{mark} {tail} · {result.iteration_count} iteration(s)",
        style="bold green" if passed else "bold red",
    )
    if result.diffstat:
        console.print()
        console.print("changes:", style="dim")
        console.print(result.diffstat, style="dim")
