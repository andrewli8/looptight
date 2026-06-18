# looptight propose — design

Date: 2026-06-18
Status: approved (Approach C), building

## Context

looptight runs a coding agent in a verify-gated loop with value-aware stopping.
The next step toward "loop engineering" is letting the loop find its own work
instead of being handed one goal. Research (see project memory) found the
"what to work on / in what order" decision is the least validated part, so this
feature stays deliberately grounded and human-gated: it only proposes tasks from
concrete, verifiable repo signals, and a human approves what runs.

## Goal

Build `looptight propose`: scan the repo for concrete signals and emit a ranked,
deduped candidate task list. No agent calls, no tokens, no side effects.

## Scope

In scope (the buildable, tested feature):
- A `propose` command and a `propose.py` module.
- Signal extractors, each a small function returning `Candidate`s:
  - `from_todos` — `TODO`/`FIXME`/`HACK`/`XXX` in source, with `file:line`.
  - `from_skipped_tests` — `skip`/`skipif`/`xfail` markers in tests.
  - `from_status_next` — the numbered list under `## Next` in `docs/STATUS.md`.
  - `from_lint` — `ruff` findings, only when `ruff` is available (guarded).
- `propose()` runs the extractors, dedups by `(location, normalized title)`, and
  ranks by a transparent source-priority heuristic.
- CLI: prints a ranked list; `--json` for machine use; `--limit N` (default 10).

Out of scope (operating procedure, reuses existing pieces):
- Executing tasks. Approved tasks run via existing `looptight run` on a branch,
  with diffs surfaced for human review. Nothing auto-merges to main.
- A standalone orchestrator. Claude Code's worktrees/agents already cover that.
- `mypy` and `from_failing_verify` extractors (easy follow-ons; deferred to keep
  v1 lean and offline-testable).

## Design

`Candidate` (frozen dataclass): `title`, `source`, `location` (file:line or None),
`suggested_verify` (str | None), `score` (float), `detail` (str).

Extractors are pure over the working directory (filesystem reads); `from_lint`
shells out to `ruff` and degrades to an empty list when `ruff` is absent, so the
test suite stays offline and deterministic.

Ranking is a documented heuristic, not a validated ordering. Source-priority
weights (high to low): failing verify (future) > type errors (future) > lint >
skipped tests > TODO/FIXME > STATUS "Next". Stable sort by weight; ties keep
discovery order. The heuristic is labeled as such in code and output.

Dedup: drop later candidates whose `(location, normalized-title)` already
appeared.

## Guardrails

- `propose` is read-only: no agent, no tokens, no writes.
- Execution stays human-gated: propose -> you approve a subset -> branch per task
  -> `looptight run` (verify-gated loop + `patience` early stop) -> you review ->
  merge or discard.
- Session spend is bounded by approved-tasks x per-task budget ($1 / 6 iters /
  patience 2 defaults). `--limit` (default 10) caps how many are surfaced.
- Skill auto-install during execution: official Vercel skills directory only,
  logged to the run report, reversible. The real install mechanism is verified
  before use, not fabricated.

## Testing

Unit tests per extractor against fixture files in a tmp repo, plus dedup and
ranking. `from_lint` is guarded so it skips cleanly when `ruff` is absent.
Matches looptight's existing pattern: small pure modules, injected collaborators,
no network.

## Open questions

- Calibrating the ranking weights against real runs (heuristic for now).
- When to add `from_failing_verify` / `from_types` (cost vs. signal value).
