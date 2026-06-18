# looptight propose — design

Date: 2026-06-18
Status: implemented; autonomous execution policy amended 2026-06-18

## Context

looptight runs a coding agent in a verify-gated loop with value-aware stopping.
The next step toward "loop engineering" is letting the loop find its own work
instead of being handed one goal. Research (see project memory) found the
"what to work on / in what order" decision is the least validated part, so this
feature stays deliberately grounded: it only proposes tasks from concrete,
verifiable repo signals. The operating agent selects and runs actionable tasks;
no human participates in the task cycle.

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
- Executing tasks. The operating agent runs selected tasks via existing
  `looptight run`, reviews the diff, verifies it, and commits and pushes each
  coherent change. This remains outside the read-only `propose` command itself.
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
- Execution is autonomous: propose -> select the highest-value actionable task
  -> `looptight run` (verify-gated loop + `patience` early stop) -> agent diff
  review -> commit and push, or discard and record the blocker.
- Session spend is bounded per task by the configured budget ($1 / 6 iterations /
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
