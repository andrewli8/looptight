# looptight goal — design

**Status:** approved design, pending implementation plan.
**Date:** 2026-06-24.

## Goal

Add a `looptight goal` command family that lets the host coding-agent session
build toward a stated project vision from 0 to 1, generating the next increment
on the fly, verify-gating each, and continuing until the goal's done-check passes
or the session's usage is spent. It is a deliberate complement to the existing
evidence-first `next` refinement loop, not a replacement.

## What it is, and is not

- **Is:** durable scaffolding around the host's generative building. It persists
  the vision, hands the host one verifiable increment at a time, gates each commit
  on a real exit code, and checks an optional deterministic done condition. It is
  `/goal` with a real verifier instead of a transcript judge, and provider-neutral.
- **Is not:** a code generator. looptight makes no model or network calls; the
  host session does all thinking and implementing. `goal` adds no provider calls.
- **Is not:** a change to `next`. The evidence-first refinement loop and its
  grounding rail are untouched. `goal` lives beside it as a separate command so the
  greenfield reach (which relaxes "must already exist in the repo") never dilutes
  the discipline of `next`.

## Core constraints (inherited, non-negotiable)

1. **No model/network calls in any looptight command.** `goal next` emits a
   directive (text) for the host; it does not generate the increment itself.
2. **The verifier is the trust anchor.** A commit is authorized only by a passing
   `looptight verify` (exit code 0). This is unchanged.
3. **Stdlib only, zero runtime dependencies.**
4. **Runtime state stays out of project history** (repo-private, like claims and
   the coordinator).

## Command surface

- `looptight goal "<vision>" [--done "<cmd>"]`
  Store and activate the goal. `<vision>` is a free-text north star. `--done` is an
  optional shell command whose exit-0 marks the goal complete (the deterministic
  early exit). Default is open-ended. Re-running replaces the active goal.
- `looptight goal next [--json]`
  Emit the next directive for the host: the vision, a note to inspect current state,
  and the instruction to make the single smallest increment that advances the vision
  and is provable by a test. If a `--done` check is set and now passes, report
  `status: done` with no directive. Increments an iteration counter.
- `looptight goal check`
  Deterministic done probe: run the `--done` command and exit 0 when the goal is
  complete, non-zero otherwise (exit 0 vacuously false / non-zero when no goal or no
  done-check is set). Designed for native loop wrappers (`/loop until: …`) and
  scripts. Changes nothing, makes no model call.
- `looptight goal status [--json]`
  Show the active goal, its done-check, and the iteration count. Changes nothing.
- `looptight goal clear`
  Deactivate and remove the goal state.
- `looptight verify` — unchanged. The commit gate.

## The loop (host-driven, provider-neutral, wrappable)

```
looptight goal "todo API with auth" --done "pytest -q"
repeat:
  looptight goal next     # -> directive: next verifiable increment, or status: done
  <host builds the increment>
  looptight verify        # exit-code gate
  <commit on pass; on fail, host fixes and re-verifies>
  # stop when `goal next` reports done, or the session usage runs out
```

The continuity is driven by the host, not by looptight, so it works in any agent
session. It is **wrappable** by each agent's native autonomy:
- Claude Code: `/goal` to run the looptight goal loop until `looptight goal check`
  exits 0, or `/loop until: looptight goal check`.
- Codex / OpenCode: their equivalent autonomous-iteration features, or the
  integration instruction block (below) that tells the host to keep looping.

A short managed instruction block is added to `CLAUDE.md` / `AGENTS.md` (idempotent
markers, same mechanism as the existing session-loop block) describing the loop so
the host runs it without re-prompting.

## Grounding model (minimal: vision string only)

No roadmap file. Each `goal next` directs the host to choose the next single
increment directly from the vision plus the current code state. Rationale: keeps
looptight small and avoids a planning artifact to maintain. The trade-off
(accepted): the verify gate carries most of the trust; there is no roadmap to score
drift against. The existing idea-eval remains available to score increments but is
not required by goal mode.

## Bootstrap (the 0-to-1 part)

On an empty or near-empty repo there is no test command yet, so the gate would be
vacuous. The first directive therefore steers the host to **scaffold the project
and establish a test harness plus a `verify` command first**, so the exit-code gate
becomes real within an iteration or two rather than building ungated for long. If
`.looptight.toml` has no `verify`, `goal next`'s directive makes "create a runnable
test command and record it" the first increment.

## Termination

Three independent stops, any of which ends the loop:
1. **Done-check passes** (`--done "<cmd>"` exits 0). Deterministic, looptight-owned.
   `goal next` returns `status: done`.
2. **Session usage spent.** Implicit: the host session simply stops when it hits its
   provider limit. looptight cannot see provider usage and does not pretend to; this
   is the host's / native wrapper's concern.
3. **No further grounded progress.** The host judges the vision met or no verifiable
   increment remains and stops calling `goal next`. A high iteration cap guards
   against runaway loops (the cap value is set in the implementation plan).

## State

A repo-private `goal.json` under the git common dir (`…/looptight/goal.json`, beside
the coordinator), holding `{schema_version, vision, done_check, created_at,
iteration}`. Never tracked, shared across worktrees, removed by `goal clear`.

## Modules (anticipated; finalized in the plan)

- `src/looptight/goal.py` — goal state read/write, the `goal next` decision
  (run the done-check, build the directive, bump iteration), and the build prompt
  constant (a `GOAL_BUILD` analog to `prompts.PLANNING_GOAL`).
- `src/looptight/prompts.py` — host-facing build directive text lives here with the
  other prompts (one source).
- `src/looptight/cli.py` + `protocol_commands.py` — the `goal` subparser and
  `cmd_goal` dispatch (positional vision to set, `next`, `check`, `status`, `clear`).
- `src/looptight/integration.py` — the managed `CLAUDE.md`/`AGENTS.md` block.
- Reuse: `verify` (the gate), `idea_eval` (optional scoring), the repo-private path
  helper from `coordinator.py`.

## Testing approach (TDD, stdlib only)

1. `goal "<vision>" --done "<cmd>"` writes repo-private state; `goal status --json`
   reflects it; `goal clear` removes it; state is untracked by git.
2. `goal next --json` returns a directive carrying the vision and a "one verifiable
   increment" instruction; the iteration counter advances.
3. With a `--done` check that passes, `goal next` returns `status: done` and no
   directive and `goal check` exits 0; with one that fails, `goal next` stays
   `active` with a directive and `goal check` exits non-zero.
4. Bootstrap: on a repo with no configured `verify`, the directive instructs
   establishing a test command first.
5. No-model-call: `goal` makes no network/model call (pure, deterministic) — same
   contract the suite already enforces for `next`/`verify`.
6. The managed integration block is present and idempotent.

## Out of scope (this spec)

- A roadmap / SPEC.md artifact (minimal grounding was chosen).
- Provider usage detection.
- A headless `goal` runner that spawns child agents, and a multi-agent goal swarm
  (possible future work; the daemon/swarm machinery could host it later).
- Enforcing increment value beyond the verify gate (value stays human-judged).
