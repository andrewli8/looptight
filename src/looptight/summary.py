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
    StopReason.BUDGET_EXCEEDED: "stopped: hit budget ceiling",
    StopReason.NO_PROGRESS: "stopped early: no measurable progress (cut losses)",
    StopReason.ESCALATED: "stopped: stuck with no progress, worth a human look",
    StopReason.NO_VERIFY: "stopped: no verify command (no verify, no loop)",
    StopReason.AGENT_UNAVAILABLE: "stopped: no coding agent found on PATH",
    StopReason.ERROR: "stopped: error",
}


def header(result: RunResult) -> str:
    verb = "driving native loop" if result.mode == "delegate" else "supplying loop"
    return f"looptight · agent: {result.agent} ({verb})"


def render(result: RunResult) -> str:
    """Full plain-text summary."""
    lines = [header(result), ""]
    for record in result.iterations:
        lines.append(f"{record.line()}   ${record.cost_usd:.2f}")

    mark = "✓" if result.passed else "✗"
    tail = _REASON_TEXT.get(result.stop_reason, result.stop_reason.value)
    lines.append("")
    lines.append(
        f"{mark} {tail} · {result.iteration_count} iteration(s) · ${result.total_cost_usd:.2f}"
    )
    if result.diffstat:
        lines += ["", "changes:", result.diffstat]
    if result.lesson:
        lines.append("")
        lines.append(f"lesson saved: {result.lesson.text}")
    return "\n".join(lines)


def render_rich(result: RunResult, console) -> None:  # pragma: no cover - thin I/O
    """Print the summary to a rich Console with green/red emphasis (E2)."""
    console.print(header(result), style="bold")
    console.print()
    for record in result.iterations:
        style = "green" if record.verify.passed else "red"
        console.print(f"iteration {record.number} → verify: ", end="")
        console.print(record.verify.short(), style=f"bold {style}", end="")
        console.print(f"   ${record.cost_usd:.2f}", style="dim")

    passed = result.passed
    mark = "✓" if passed else "✗"
    tail = _REASON_TEXT.get(result.stop_reason, result.stop_reason.value)
    console.print()
    console.print(
        f"{mark} {tail} · {result.iteration_count} iteration(s) · ${result.total_cost_usd:.2f}",
        style="bold green" if passed else "bold red",
    )
    if result.diffstat:
        console.print()
        console.print("changes:", style="dim")
        console.print(result.diffstat, style="dim")
    if result.lesson:
        console.print(f"lesson saved: {result.lesson.text}", style="cyan")
