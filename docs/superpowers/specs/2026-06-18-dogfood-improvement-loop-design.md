# Dogfood self-improvement loop

Date: 2026-06-18
Status: approved

## Goal

Use looptight to improve its own repository during the current working session.
Work proceeds one evidence-backed task at a time, with each verified improvement
committed and pushed directly to `main`.

## Cycle

1. Run `looptight propose` and discard candidates already recorded as blocked or
   requiring unavailable external evidence.
2. If no actionable proposal remains, identify one task from concrete repository
   evidence: failing checks, a safety gap, an untested critical path, inconsistent
   documentation, or observable CLI friction.
3. Run the task through the existing `looptight run` command and configured
   agent. Do not add a second orchestrator or persistent daemon.
4. The operating agent reviews the resulting diff, then runs
   `uv run pytest -q` and `uv run ruff check`.
5. Commit a coherent verified change with a conventional commit and push it to
   `origin/main`.
6. Repeat through `looptight improve`; when grounded tasks are exhausted, use a
   fresh evidence-based agent audit rather than stopping for lack of proposals.

The session stops only when its session spend threshold is reached, the provider
refuses further calls, the user interrupts it, or a Git safety operation fails.

## Task selection

`looptight propose` is the primary source because its candidates are traceable
to repository signals. When that queue is exhausted, supplemental tasks must
cite observable evidence in the code, tests, documentation, or CLI behavior.
Task generation must not invent external tool behavior or add work merely to
keep the loop busy.

Prefer user-facing correctness and safety over test-count growth. Keep changes
small enough to verify and review independently.

## Guardrails

- Start each task from a clean working tree.
- Process one task at a time; inspect all agent-produced changes before commit.
- Task selection, diff review, commit, push, and continuation are autonomous.
  No human participates in the task cycle.
- Retain the configured `$1` budget, six-iteration cap, and patience of two.
- Treat the configured verify command as the pass/fail contract, with Ruff as an
  additional required check.
- Do not add dependencies without a specific, documented need.
- Do not make speculative changes based on unobserved external CLI behavior.
- Do not use destructive Git operations or force-push.
- Push only coherent changes that pass verification.

## Documentation

Avoid per-iteration narration in tracked files. Add a concise run summary only
when it records a landed change, a new decision, or a newly discovered blocker.
Do not repeat blockers already present in `REVIEW-QUEUE.md` or `docs/STATUS.md`.

## Success criteria

- Improvements are executed through looptight rather than only edited manually.
- Every pushed code change passes pytest and Ruff.
- Each task has a concrete evidence trail and a focused commit.
- No task bypasses budget, iteration, verification, or Git safety boundaries.
- Repeated audit prompts avoid padding and duplicate documentation while keeping
  the session active until an explicit terminal condition occurs.
