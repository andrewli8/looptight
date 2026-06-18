# looptight — working notes for agents

A thin, portable learning layer for coding agents: a verify-gated loop with
durable lessons, across Claude Code, Codex, and opencode. Architecture lives in
`docs/architecture.md`; status in `docs/STATUS.md`.

## Principles (in priority order)

1. **Simple and efficient beats clever.** The product's edge is focus. If a
   change grows the surface past one page or adds a second mandatory concept, it
   is probably wrong. No new runtime dependencies without a strong reason (today:
   only `rich`).
2. **Lightweight.** Many small, focused files (200-400 lines). Pure functions
   with injected collaborators so the control flow stays testable offline.
3. **Verify is the contract.** No verify, no loop. Both supply and delegate paths
   run `verify`; it is the ground-truth oracle. Never self-grade.
4. **Delegate, don't duplicate.** Where the host agent already provides something
   (worktrees, connectors, native loops), drive it; don't rebuild it here.
5. **Immutable data.** Frozen dataclasses in `types.py`; return new objects.

## Autonomous-loop discipline

- **Propose, then approve.** `looptight propose` surfaces tasks from concrete
  repo signals; a human approves what runs. Substantive work goes on a branch
  and is reviewed before main.
- **Escalate, don't guess.** If a change can't be cheaply verified (e.g. it
  depends on an external CLI's output format we can't observe), stop and flag it
  for a human instead of inventing an implementation.
- **Guard token cost.** Low caps, cheap-model reflection, value-aware early stop
  (`patience`). A second opinion (sub-agent) is worth spending on only where it
  pays off.
- **Stay the engineer.** Verification stays human. Don't let the loop outrun
  understanding.

## Workflow

- TDD: write the test first, then the implementation.
- Before claiming done: `uv run pytest -q` and `uv run ruff check` must be clean.
- Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).
- After each verified change, commit and push to `main`.
