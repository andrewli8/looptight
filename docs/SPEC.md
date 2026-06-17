# Loop Harness: Mandatory Feature Spec (v1, revised)

> Working name: **looptight**.
> A portable learning layer for coding agents. It runs on the agent you already
> have (Claude Code, Codex CLI, opencode), drives the native loop where one
> exists, supplies one where it doesn't, and makes every run teach the next.

This document is the source of truth for what v1 must do. Implementation status
is tracked in [`STATUS.md`](STATUS.md).

---

## Positioning (one line)

**Your coding agent on autopilot, across Claude Code, Codex, and opencode, that gets smarter every run.**

It does **not** reinvent the loop. Where the agent already ships an eval-gated
loop (Codex `/goal`), it drives that. Where it doesn't, it supplies one. On top
of all of them it adds the two things none of them do: **one consistent
interface across agents**, and **durable lessons that compound across runs**.

---

## Design principles (non-negotiable)

1. **Delegate, don't duplicate.** Native loops are converging. Where one exists,
   drive it. Supply a loop only where the agent lacks one. Never compete with the
   platform's own loop.
2. **The eval is the contract.** No verify command, no loop. Identical whether we
   delegate or supply.
3. **Lessons compound.** Every failed-then-fixed run leaves a durable lesson in
   the agent's own memory file. This is the headline, not a sub-feature.
4. **Safe to try.** No cost blowups, no unrecoverable edits. "Safe" is part of
   "easy."
5. **Legible in one gif**, and the gif leads with *"runs on your agent and got
   smarter,"* not *"it loops."*

---

## Mandatory features (v1)

### A. Onboarding & first run
- **A1 Single-command install.** One binary / `uvx` / `npx` / `pipx`.
- **A2 Zero-config first run.** Auto-detect the installed agent (PATH) and the
  project's test command.
- **A3 One concept to learn: `verify`.** `init` writes a minimal config and
  explains `verify` in two lines.
- **A4 Use the agent you already have (auth-neutral).** Works on API-key *or*
  subscription auth; not locked to one provider's flow.

### B. Loop: delegate or supply
- **B1 Detect & drive the native loop** (Codex `/goal`).
- **B2 Supply the loop where absent** (Claude Code, opencode): run → verify →
  continue, with budget + persistence.
- **B3 Verify is the ground-truth oracle.** Pass/fail or numeric score.
- **B4 Normalized surface.** Same flags, caps, and summary across backends.

### C. The learning layer (*the differentiator*)
- **C1 Reflection on failure.** Distill one short, specific lesson from
  (transcript + verify output).
- **C2 Persist lessons into the agent's native memory file.**
- **C3 Lessons compound** across runs and goals.
- **C4 Lesson hygiene.** Scoped, deduped, one-command prunable.

### D. Safety & trust
- **D1 Hard iteration cap + cost ceiling**, low defaults, clean stop.
- **D2 Live counter:** iteration, running cost estimate, last verify result.
- **D3 Cheap-model routing for reflection.**
- **D4 Per-iteration git checkpoint + revert.**

### E. Output & legibility
- **E1 Readable run summary** (cross-backend).
- **E2 Gif-able output.** Clear `iteration N → verify: PASS/FAIL` lines.

### F. Portability (*core, not footnote*)
- **F1 Adapter interface.** Each agent drives the native loop or supplies one.
- **F2 Auth-neutral.**
- **F3 (later) ACP transport.** Post-v1.

---

## Explicitly deferred (NOT in v1)

- Rebuilding loops the native tools already provide (explicit non-goal).
- Competence predictor / task triage (v2).
- Multi-agent / DAG orchestration.
- Plugin marketplace / extensions.
- Web UI / dashboard.
- Weight tuning / RL self-modification.

---

## v1 success criteria (measurable)

- **One interface, three agents:** the same command works on Claude Code, Codex,
  and opencode.
- **Time-to-first-successful-loop < 2 minutes** from install on a repo with tests.
- **Flagship demo leads with the gap, not the loop:** the *same* command on Claude
  Code and on Codex; then a second, similar task that visibly benefits from a
  lesson written during the first run.
- **A default run cannot exceed the cost ceiling** without explicit `--budget`.
- **README opens with the differentiation** (portability + compounding lessons).

---

## Pre-launch discipline

Pick the launch date and the flagship demo first. Everything not required to make
*that one demo* land is post-launch. This spec is the permission to stop adding.
