# Architecture

Looptight is a provider-neutral task and validation protocol around a native
coding-agent session.

```text
project evidence → propose → next + atomic claim → native agent edits
                                             ↓
commit ← passing verdict ← verify command ← review
```

## Decision boundaries

- `discovery.py` reads concrete repository signals into candidate tasks.
- `ranking.py` dedupes and orders those candidates by a transparent heuristic.
- `propose.py` composes discovery and ranking into the public candidate list.
- `tasks.py` turns the first available candidate into versioned `next` output.
- `claims.py` prevents duplicate work across Git worktrees using private atomic
  files under the repository's common Git directory.
- `verify.py` executes the project contract and distinguishes a valid pass/fail
  verdict from timeout or launch errors.
- `commands.py` exposes the protocol as text and versioned JSON.
- `integration.py` installs the same small loop instruction for Codex, Claude
  Code, and OpenCode.

These modules make no agent or network calls. Provider authentication, model
selection, context, and usage limits remain inside the active agent CLI.

## Optional headless path

`loop.py` and `adapters/` remain as an explicit `run --headless` compatibility
path. They launch one provider CLI iteration, run the same verifier, and repeat
under an iteration cap. They do not reflect, generate lessons, estimate costs,
or select repository work.

The deprecated `improve` command is a migration message only; there is no
second continuous-loop engine.

Single-round `swarm.py` is a deterministic, explicit headless manager over the
same task, claim, loop, and verifier primitives. It creates isolated Git
worktrees, runs a bounded worker pool, and serializes verified integration. It
does not use a manager model, invent task graphs, or bypass provider-native
limits.

With explicit `swarm --continuous`, the selected provider CLI supplies one
planning pass only after grounded work is exhausted. Planning occurs in another
isolated worktree and may update only the bounded `docs/STATUS.md` Next list.
Looptight validates task shape, repository evidence paths, and the verifier
before merging the plan and starting another deterministic swarm round.

## Repository coordinator

Many Looptight sessions can share one repository safely:

```text
many sessions → shared task queue → isolated worktrees → verify → one-at-a-time Git integration
```

A repository-private SQLite database (`<git-common-dir>/looptight/coordinator.db`,
WAL) holds run identity, short transactional **task leases** fenced by generation,
proposal deduplication, and durable integration/publication queues (`coordinator.py`).
Planning and worker execution stay parallel; only Git integration serializes,
behind a repository-private advisory lock guarding one coordinator-owned **detached**
integration worktree (`integration_queue.py`). User worktrees are never reset or
removed, and nothing force-pushes.

Each verified worker enqueues a fenced integration; the `Integrator` drains the
queue oldest-first under the lock — merging in the coordinator worktree, verifying,
and advancing the target ref by compare-and-swap. Every merge carries a
`Looptight-Integration-ID` trailer, so `reconcile()` resolves any integration left
mid-flight by a crash to exactly one reachable result. Publication is separate and
equally idempotent: it fetches first and finalizes without a second push when the
remote already has the result, pushing only the exact result SHA.

Scope and rules: coordination is **local to one machine and filesystem**. Activation
is explicit — `looptight migrate` (`Coordinator.open(activate=True)` →
`activate_from_legacy`) refuses while any legacy file claim is still live, then writes
a `coordinator-format.json` marker after which legacy file claims fail closed. It is
idempotent and errors outside Git.
Existing `next`/`status`/`swarm` JSON keys are unchanged; coordinator counts are
projected **additively** (a `coordinator` block on `status`). The integration lock
has a bounded timeout; failed/conflicting work is retained for recovery.

## Who orchestrates

A continuous run has three roles, and only two are provider agents:

- **Orchestrator** — the `looptight` process itself (`run_continuous_swarm`, or
  the single-agent `run_loop`). It is deterministic Python that claims tasks,
  spawns workers, runs the verifier, and merges. It makes no model or network
  calls, so it consumes no provider allowance.
- **Workers** — the provider CLI invocations the orchestrator spawns, one per
  claimed task in its own worktree. These are the agents that spend allowance.
- **Planner** — a single provider CLI invocation, spawned only when the grounded
  queue is empty, to refresh the bounded plan.

The orchestrator is not an agent reasoning about what to do next; the agents are
the workers and the occasional planner it launches.

A fourth role is optional and also deterministic Python: the **supervisor**
(`daemon.py`, `looptight daemon`). `run_continuous_swarm` is bounded — it returns
when the backlog is exhausted, a usage limit persists, or a fault occurs. The
supervisor reruns it forever, choosing the gap before the next cycle from the
run's structured `SwarmResult.reason` (immediate after merged progress, an idle
poll when there is nothing to build, capped exponential back-off on a fault). It
spends no allowance itself and is the piece that turns the bounded loop into
genuine 24/7 operation on a host that stays up. See [daemon.md](daemon.md).

## Idea generation

A self-improvement loop should not stop the moment the grounded queue empties.
By default, both queue-driven loops generate new evidence-backed tasks instead:

- **Session-native loop:** when `next` finds no grounded work it returns `no_work`
  with a `generate_ideas` directive (the shared `prompts.PLANNING_GOAL`). The
  installed instructions tell the **host session agent** to write 1-6 grounded
  `## Next` tasks and continue. looptight makes no model call — the host session,
  already running, does the thinking, preserving the no-calls contract.
- **`swarm --continuous`:** the deterministic orchestrator invokes the **planner
  subagent** when work is exhausted (existing behavior).

`ranking.py` weights human/planner-curated sources (`task-file`, `status-next`)
above automated signals (`lint`, `todo`) so generated and curated intent is
claimed before incidental nits. Generation is bounded by the planner prompt's
grounding rail — no evidence, no task — so the loop still terminates honestly, and
`--no-ideas` / `idea_generation = false` restores stop-on-empty everywhere.

### Metacognitive monitor and control (Phase 2)

A lightweight monitor, self-model, and control layer lets looptight learn from
past idea outcomes without storing state outside the repository or the
coordinator.

**Idea identity.** `idea_identity.py` computes a deliberately lossy 12-hex
identity for each candidate (`idea_id`). It is stable across line moves and
minor title rewording, while keeping genuinely different ideas distinct.
Both the write path (recording outcomes) and the read path (building the
self-model) use the same function, so the two cannot drift.

**Outcome recording.** A `landed` outcome is recorded as a
`Looptight-Outcome: <idea_id> landed` git trailer on the integration commit
(`integration_queue.py`). It is verified structurally: only commits reachable
from the target ref are scanned, so a trailer on an unmerged branch never
counts. A `failed` outcome is recorded locally in the coordinator's `experience`
table (`coordinator.py`) and is never pushed.

This asymmetry is deliberate. Positive learning (what worked) is shared via git
history and is structurally verifiable by any session. Negative learning (what
failed recently) is local to one machine: it guides the current session without
risking incorrect suppression in other environments or polluting the shared
history.

**Self-model.** `experience.py` builds an in-memory `Model` by unioning
verified-landed counts (read from git log) with recent local failures (read from
the coordinator). The model carries per-idea counts and per-category aggregates.
It is advisory: callers degrade to default behavior when the model is empty or
the coordinator is unavailable.

**Advisory control.** Three mechanisms apply the model without ever overriding
the verifier:

- `propose.py` suppresses candidates whose idea has reached the cooldown
  failure threshold (configurable, default 2 recent failures within 24 hours).
- `ranking.py` scales each source's base weight by a clamped category yield
  factor (floor 0.5, ceiling 1.08) computed from landed and failed counts, so
  a boosted automated source stays below the next curated tier.
- `prompts.py` injects a bounded experience note (top failing and landing
  idea IDs) before the grounding rail when building the planning prompt, used
  by both the swarm planner and the session-native directive.

Deferred items (churn detection, shared negative learning, session-native
writes, and EVOC-style value-aware scoring) are documented in `docs/SPEC.md`.

## Usage-limit resume

Provider-native usage limits stay authoritative (`SPEC.md`): looptight never
counts tokens or tracks billing. With the opt-in `--resume-on-limit`, the
deterministic orchestrator *recognizes* a usage/rate limit the provider reported
in its own output (`limits.py`), then waits and resumes rather than stopping. It
prefers the reset interval the provider named and otherwise backs off
exponentially, capping any single wait so a long reset is handled by re-polling.
The swarm applies this between rounds; the single-agent supply loop applies it
between iterations, where a wait costs no iteration-cap slot. Genuine
verification failures and crashes still stop the run.

## Validation order

1. Validate configuration and task evidence.
2. Atomically claim the task when Git-private state is available.
3. Let the native agent implement it.
4. Require the verifier to execute normally.
5. Treat only exit zero as pass.
6. Review the diff and commit; remove completed evidence from the bounded plan.

Heuristics can rank tasks or identify stalled progress. They cannot grant a
passing verdict.
