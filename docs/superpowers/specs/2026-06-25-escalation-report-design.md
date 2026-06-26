# Escalation report design

**Status:** approved design, pending implementation plan.

**Goal:** When the value-aware stopping controller cuts a headless `run` short,
tell the human *why* and *where* — the specific failures that never cleared plus
the progress trajectory — instead of only `stopped: stuck with no progress, worth
a human look`. Surface the same evidence in a new `run --json` contract.

## Context

`metacog.py` already implements Phase 1 of the metacognitive planner: after each
failed verify, `assess(history, patience)` reads the progress-signal trajectory
and returns one of `CONTINUE`, `STOP_NO_PROGRESS` (improved then plateaued), or
`ESCALATE` (never moved the needle). `run_loop` (in `loop.py`) acts on these,
setting `StopReason.NO_PROGRESS` or `StopReason.ESCALATED` and breaking.

Today both early stops render only a one-line tail in `summary.py`
(`stopped early: no measurable progress` / `stopped: stuck with no progress,
worth a human look`) plus the per-iteration `iteration N → verify: FAIL` lines.
The human is told *that* to look but not *why* or *where*. This is the Chow's
reject-rule gap from the research direction (memory
`looptight-metacog-planner-design`): when you escalate, surface the evidence.

`run` currently has **no** `--json` flag, and `RunResult` has no serialization —
so `run` is the one command that violates the SPEC "every command supports
`--json`" contract. This design closes that gap as part of the work.

## Scope

**In:**
- A structured `Escalation` report (persistent failures + trajectory) attached to
  `RunResult` on **both** early-stop reasons (`ESCALATED` and `NO_PROGRESS`).
- Runner-agnostic extraction of "persistent failures": failure-shaped output lines
  present in every iteration, normalized for volatile tokens, with a final-iteration
  fallback.
- Rendering the report in the human `run` summary (`summary.render` /
  `render_rich`).
- A new `run --json` contract: a `--json` flag and a bounded `RunResult.as_dict()`
  that includes the escalation.

**Out (deferred, not in this spec):**
- Bringing the stall signal to the session-native `next`/`verify` path.
- A real token-cost (EVOC) term in `assess` (still uses `patience`).
- Any opt-in LLM monitor / self-consistency tier (Phase 2).
- Threading escalation evidence through `swarm` per-worker output.

## Data model (`types.py`)

A new frozen dataclass:

```python
@dataclass(frozen=True)
class Escalation:
    kind: str                              # "escalated" | "no_progress"
    iterations: int                        # iterations run before the early stop
    trajectory: tuple[float | None, ...]   # per-iteration progress signal (most recent last)
    persistent_failures: tuple[str, ...]   # failure lines present every iteration (capped)
    summary: str                           # one human sentence
    persisted: bool = True                 # False when persistent_failures is a final-iteration fallback

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "iterations": self.iterations,
            "trajectory": list(self.trajectory),
            "persistent_failures": list(self.persistent_failures),
            "summary": self.summary,
            "persisted": self.persisted,
        }
```

`RunResult` gains one optional field, leaving all existing fields and order
unchanged:

```python
escalation: Escalation | None = None
```

`MAX_PERSISTENT_FAILURES = 10` caps the list; truncation is reported in `summary`
("… and N more"). Each failure line is itself length-capped
(`MAX_FAILURE_LINE = 200`) to stay bounded, matching the verify-output ethos.

## Extraction (`metacog.py`)

Three new pure functions, no model calls:

```python
def _failure_lines(output: str) -> set[str]:
    """Failure-shaped lines from one verify output, normalized so the same
    failure matches across runs."""
```
- Keep a line if it matches `_FAILURE_LINE_RE`, a broad case-insensitive pattern:
  `FAILED`, `FAIL:`, `ERROR`, `AssertionError`, `Traceback`, a leading `✗`/`✕`/
  `×`, or `not ok` (TAP). This spans pytest, unittest, jest/vitest, go test, and
  mocha/tap.
- Normalize volatile tokens on the kept line via `_normalize_failure`:
  strip a trailing duration (`\s*\(?\d+(\.\d+)?\s*m?s\)?$`), strip `in 1.23s`
  suffixes, and replace hex addresses (`0x[0-9a-fA-F]+`) with `0xADDR`. Collapse
  runs of whitespace. Truncate to `MAX_FAILURE_LINE`. Keep digits inside paths and
  test names (they are identity, not noise).

```python
def persistent_failures(records: list[IterationRecord]) -> tuple[tuple[str, ...], bool]:
    """Returns (lines, persisted). `persisted=True`: the lines are present in
    every iteration's failure set (a real "never cleared"). `persisted=False`:
    the intersection was empty, so the lines are the final iteration's failures
    (a "most recent" fallback). Empty tuple when nothing parses anywhere."""
```
- Compute `_failure_lines` per iteration. Intersect across all iterations. If the
  intersection is non-empty, return `(sorted(intersection)[:MAX], True)`. Else if
  the final iteration has any failure lines, return
  `(sorted(final)[:MAX], False)`. Else return `((), True)` (nothing parsed).
- Determinism: sort the lines (stable output for tests and diffs).

```python
def build_escalation(records, history, stop_reason) -> Escalation:
    """Assemble the report for an early stop. `stop_reason` is the StopReason that
    fired (ESCALATED or NO_PROGRESS); maps to kind."""
```
- `kind = "escalated" if stop_reason is StopReason.ESCALATED else "no_progress"`.
- `iterations = len(records)`.
- `trajectory = tuple(history)`.
- `(failures, persisted) = persistent_failures(records)`.
- `summary`: a single sentence built from the known progress signal. Examples:
  - escalated, with failures: `never improved across 5 iterations (stuck at 8
    failures); 3 never cleared`.
  - no_progress, with failures: `improved then stalled over 5 iterations; 3
    failures remain`.
  - no failures parsed: append `no specific failures parsed; see the final
    iteration output`.
  - fallback (`persisted=False`): the failures are introduced as `most recent
    failures (none persisted across all iterations)`.
  The numbers come from `history` (first/best/last known signal); when the signal
  is all `None`, the count phrases are omitted rather than fabricated.

## Wiring (`loop.py`)

At the two early-stop branches in the supply loop, build and attach the report
before constructing the final `RunResult`:

```python
if decision is Decision.ESCALATE:
    stop = StopReason.ESCALATED
    escalation = build_escalation(records, progress, stop)
    break
if decision is Decision.STOP_NO_PROGRESS:
    stop = StopReason.NO_PROGRESS
    escalation = build_escalation(records, progress, stop)
    break
```

`escalation` defaults to `None` and is passed into the final `RunResult(...)`.
`records` and `progress` already exist at this point — no new collection. SUCCESS,
`ITERATION_CAP`, `NO_VERIFY`, `AGENT_UNAVAILABLE`, and `ERROR` stops leave
`escalation=None`. The delegate (native) loop does not run the controller, so it
never sets an escalation. `patience = 0` disables the controller, so no early stop
and no report.

## Rendering (`summary.py`)

When `result.escalation` is present, `render` and `render_rich` append an additive
block after the existing tail line (existing lines unchanged). A shared helper
`_escalation_lines(escalation) -> list[str]` builds:

```
why escalated: never improved across 5 iterations (stuck at 8 failures); 3 never cleared
failures that never cleared:
  - FAILED tests/test_auth.py::test_login - AssertionError: expected 200
  - FAILED tests/test_auth.py::test_logout - KeyError: 'session'
  - FAILED tests/test_billing.py::test_refund - assert 0 == 1
```

- Header line is the `escalation.summary`, prefixed `why escalated:` for
  `escalated` and `why stopped early:` for `no_progress`.
- The list header is `failures that never cleared:` when `persisted`, else
  `most recent failures:`.
- Omit the list entirely when `persistent_failures` is empty (the summary already
  says none parsed).
- `render_rich` styles the block dim/yellow; plain `render` is unstyled. Both call
  the same `_escalation_lines` so they cannot drift.

## `run --json` contract (`cli.py`, `commands.py`, `types.py`)

- `cli.py`: add `p_run.add_argument("--json", action="store_true", ...)`.
- `types.py`: add `RunResult.as_dict()` — a bounded, versioned dict:
  ```python
  {
    "command": "run",
    "schema_version": 1,
    "goal": ..., "agent": ..., "mode": ...,
    "stop_reason": self.stop_reason.value,
    "passed": self.passed,
    "iterations": [
      {"number": r.number, "passed": r.verify.passed,
       "status": r.verify.status, "exit_code": r.verify.exit_code,
       "score": r.verify.score}
      for r in self.iterations
    ],
    "diffstat": self.diffstat,
    "error": self.error,
    "returncode": self.returncode,
    "escalation": self.escalation.as_dict() if self.escalation else None,
  }
  ```
  Per-iteration `verify.output` is **not** serialized (unbounded); the escalation
  already distills the persistent failures. This keeps the JSON bounded.
- `commands.py` `cmd_run`: when `args.json`, `print(json.dumps(result.as_dict(),
  sort_keys=True))` and return the existing exit code; otherwise `render_rich` as
  today. The exit code is unchanged (`0` on SUCCESS, else `1`).

## Error handling / edge cases

- Nothing parses in any iteration → `persistent_failures` empty → summary notes
  "no specific failures parsed"; list omitted. No fabrication.
- Intersection empty, final iteration has failures → fallback list, `persisted=
  False`, labeled "most recent."
- Degenerate `< 2` iterations (the controller normally needs `patience+1` signals,
  but guard anyway) → `build_escalation` still returns a valid report; `iterations`
  reflects the real count.
- All-`None` trajectory (verify output never parsed a signal) → count phrases
  omitted from the summary; the report still lists any failure lines.
- Output stays bounded: at most `MAX_PERSISTENT_FAILURES` lines, each at most
  `MAX_FAILURE_LINE` chars.

## Testing (TDD)

Unit (`tests/test_metacog.py`, extending the existing file):
1. `_failure_lines` extracts pytest `FAILED …`, jest `✕ …`, and go `--- FAIL: …`
   lines; ignores passing/noise lines; `_normalize_failure` makes the same failure
   with a differing trailing duration compare equal.
2. `persistent_failures` — a failure present in all iterations is persistent
   (`persisted=True`); one that cleared in the final iteration is excluded; an
   empty intersection falls back to the final iteration's failures
   (`persisted=False`); nothing-parses returns `((), True)`.
3. `build_escalation` — `kind` is `escalated` vs `no_progress` per stop reason;
   `iterations`/`trajectory` populated; summary sentence matches the trajectory;
   all-`None` trajectory omits the count phrases.

Integration (`tests/test_loop.py`):
4. A run that never improves attaches an `escalation` with `kind="escalated"`; one
   that improves then stalls attaches `kind="no_progress"`; a SUCCESS run and an
   iteration-cap run leave `escalation=None`.

Rendering (`tests/test_summary.py`):
5. `render` prints the `why …` line and the failure list when an escalation is
   present, and is unchanged (no block) when it is absent.

CLI (`tests/test_cli.py`):
6. `run --json` emits the `as_dict` JSON including the `escalation` object (or
   `null`), with `schema_version` and `stop_reason`; existing human `run` output
   is unchanged without `--json`. The per-iteration objects carry no `output` key
   (bounded contract).

Gate: `looptight verify --json` → `pass` before each commit. Update
`docs/SPEC.md`'s output contract to note `run --json` and the `escalation` object,
guarded by the existing doc-accuracy test pattern.

## Guardrails honored

- Stdlib-only; the report makes no model or network calls (it reads data the loop
  already collected).
- `verify` stays the oracle: the controller only gates iteration and now explains
  itself; it never picks a "winner" from confidence.
- Additive contracts: existing `RunResult` fields, human summary lines, and exit
  codes are unchanged; `escalation` is optional and `run --json` is new surface.
- Bounded output, matching the verifier-truncation discipline.
