# Session-native stall signal design

**Status:** approved (autonomous goal directive), pending implementation.

**Goal:** Bring value-aware stopping to the session-native `verify` path. The
headless `run` loop already stops early when the verifier stops making progress
and explains why (the escalation report). The default path people actually use —
`next` / `verify` driven by the host agent or a `/loop` wrapper — has no stall
detection, because each `verify` runs as a separate process with no memory of the
trajectory. So an interactive or autonomous loop can grind for many iterations
spending the user's tokens with nothing telling it "you stopped making progress
three tries ago." This persists the trajectory between `verify` calls and surfaces
a stall verdict, reusing `assess` and the escalation evidence.

## Scope

**In:**
- A repo-private, per-worktree trajectory store written between `verify` calls.
- `verify --patience N` (opt-in, mirroring `run --patience`): when set, `verify`
  records the progress signal + failure lines, and `verify --json` carries an
  additive `stall` object with the `assess` decision and, when stalled, the
  escalation evidence (the failures that never cleared).
- Reset semantics: a passing verify clears the trajectory; a changed verify
  command or a stale gap (older than 30 min) starts a fresh attempt.

**Out:**
- Any change to the default `verify` (patience 0 = byte-for-byte unchanged: no
  state file, no `stall` field).
- `next` behavior, the headless `run` loop (already has this), swarm, the real
  EVOC token-cost term, the opt-in LLM monitor.

## Contract note

SPEC says `verify` "reads the repository and runs your test command, nothing
else." The trajectory store is **opt-in** (`--patience N`, default 0) and writes
only repo-private, Git-ignored state (same class as claims / swarm UI state), so
the default contract is preserved. Documented in SPEC's output contract.

## Data flow

```
looptight verify --patience 3 --json
  → run_verify(command)                                  (unchanged oracle)
  → trajectory.record(root, command, signal, failures, passed)
       passed?  → clear the store, stall = null
       else     → append {signal, failures}; reset first if command changed
                  or the last entry is stale (>30 min)
  → assess([entry.signal ...], patience)
       CONTINUE          → stall = {"decision": "continue", "escalation": null}
       STOP_NO_PROGRESS/ → stall = {"decision": ..., "escalation": <report>}
       ESCALATE             where the report is built from the stored failure sets
  → verify JSON gains an additive "stall" key (null without --patience)
```

## Components

- **New `src/looptight/trajectory.py`** — the per-worktree store:
  - `_path(root)` uses `git rev-parse --git-dir` (per-worktree, *not*
    `--git-common-dir`, so parallel worktrees never share a trajectory) →
    `<git-dir>/looptight/verify-trajectory.json`.
  - `record(root, command, signal, failures, *, passed, now=None) -> list[Entry]`:
    clears on pass; otherwise appends `{signal, failures}` after resetting when the
    stored command differs or `now - updated_at > _STALE_AFTER_S` (1800). Returns
    the resulting entries (most recent last). Tolerant reads (a corrupt/non-UTF-8
    file resets), atomic writes (tmp + `os.replace`, unlink on failure) — matching
    goal.py / ui.py.
  - `clear(root)`.

- **`metacog.py`** — factor the cross-iteration failure intersection so both paths
  share it:
  - `persistent_from_sets(failure_sets: list[set[str]]) -> (tuple[str,...], bool)`
    (the current `persistent_failures` body, operating on pre-extracted sets).
  - `persistent_failures(records)` becomes a thin wrapper over it.
  - `escalation_from_signals(history, failure_sets, stop_reason) -> Escalation` so
    the session-native path can build the same report from stored data (no
    `IterationRecord`s available across processes).

- **`protocol_commands.py` `cmd_verify`** — when `patience > 0`: extract
  `progress_signal(result)` and `_failure_lines(result.output)`, call
  `trajectory.record`, run `assess`, and attach the `stall` object to the JSON.
  Human (non-`--json`) output gains one concise line when stalled
  (`stalled: <summary>`), nothing otherwise.

- **`cli.py`** — add `--patience N` to the `verify` subparser (same help as `run`).

## Edge cases

- `patience == 0` (default): `record` is never called; no file; no `stall` field.
- Not a Git repo: `_path` returns None; `record` no-ops, returns `[]`; `stall` is
  `null` (the feature needs Git-private state).
- Corrupt/non-UTF-8 store: treated as empty (fresh attempt), never raises.
- Stale gap or command change: history resets so an old, unrelated attempt never
  produces a false stall.
- Output stays bounded: stored `failures` use the existing `_failure_lines` cap
  discipline; the escalation reuses `MAX_PERSISTENT_FAILURES` / `… and N more`.

## Testing (TDD)

- `tests/test_trajectory.py`: record appends and returns history; a passing verify
  clears it; a changed command resets; a stale `updated_at` resets; a corrupt file
  resets; non-Git dir no-ops; the write is atomic (patched `os.replace` failure
  leaves no `.tmp`, original intact).
- `tests/test_metacog.py`: `persistent_from_sets` matches the record-based result;
  `escalation_from_signals` builds the same report shape.
- `tests/test_cli.py`: `verify --patience` accumulates across calls and the JSON
  `stall.decision` goes `continue → stop_no_progress/escalate` as a stuck sequence
  repeats; a passing verify resets it; `verify --json` without `--patience` has no
  `stall` key (or `null`) and is otherwise unchanged.
- `tests/test_docs.py`: SPEC output contract documents `verify --patience` and the
  `stall` object.

Gate: `looptight verify --json` → `pass` before each commit.

## Guardrails

- Stdlib-only; no model or network calls (reads data already produced by the
  verifier). Opt-in, default contract unchanged. Atomic, tolerant, per-worktree
  state. Reuses `assess` + the escalation report rather than duplicating logic.
