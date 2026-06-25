# Architecture

looptight is a provider-neutral task and validation protocol wrapped around a
native coding-agent session. The core path:

```text
project evidence --> propose --> next (+ atomic claim) --> agent edits code
                                                                |
   commit  <--  passing verdict  <--  verify command  <--  review the diff
```

## Core modules

These modules make no agent or network calls. Provider authentication, model
choice, context, and usage limits stay inside the active agent CLI.

| Module | Responsibility |
|--------|----------------|
| `discovery.py` | read concrete repo signals into candidate tasks |
| `ranking.py` | dedupe and order candidates by a transparent heuristic |
| `propose.py` | compose discovery and ranking into the public candidate list |
| `tasks.py` | turn the top candidate into versioned `next` output |
| `claims.py` | prevent duplicate work across worktrees with private atomic files |
| `verify.py` | run the project contract; tell a real pass/fail from timeout/launch errors |
| `goal.py` | store a build vision and hand the host one verify-gated increment at a time |
| `grounding.py` | check that a task's `Evidence:` anchors resolve to real files |
| `idea_eval.py` | score a generated batch on groundedness, area spread, and distinctness |
| `commands.py` | expose the protocol as text and versioned JSON |
| `integration.py` | install the same loop instruction for each detected agent |
| `skill.py` | install a Claude Code skill so the agent discovers looptight in any session |

## Who does what in a continuous run

A continuous run has four roles. Only two of them are agents that spend
provider allowance:

```text
looptight  (deterministic Python, makes no model calls, spends $0)
|
|-- supervisor    daemon.py: reruns the swarm forever               [$0]
|-- orchestrator  swarm.py / loop.py: claim, verify, merge          [$0]
|
+-- spawns your provider CLI:
    |-- workers   one per task, edit code in isolated worktrees     [spends allowance]
    +-- planner   refreshes the plan, only when the queue is empty  [spends allowance]
```

The orchestrator is not an agent reasoning about what to do next. It is plain
Python that claims tasks, spawns workers, runs the verifier, and merges. The
agents are the workers and the occasional planner it launches.

The supervisor (`looptight daemon`) exists because `run_continuous_swarm` is
bounded: it returns when the backlog is exhausted, a usage limit persists, or a
fault occurs. The supervisor reruns it forever, picking the gap before the next
cycle from the run's structured `SwarmResult.reason` (immediate after merged
progress, an idle poll when there is nothing to build, capped exponential
back-off on a fault). It is the piece that turns a bounded loop into real 24/7
operation on a host that stays up. See [daemon.md](daemon.md).

## Headless paths

`loop.py` and `adapters/` are the explicit `run --headless` compatibility path.
They launch one provider CLI iteration, run the same verifier, and repeat under
an iteration cap. They do not reflect, generate lessons, estimate cost, or pick
repository work. The deprecated `improve` command is now just a migration
message; there is no second loop engine.

Single-round `swarm.py` is a deterministic headless manager over the same task,
claim, loop, and verifier primitives:

```text
grounded queue
   |--> worktree A --> worker --> verify --+
   |--> worktree B --> worker --> verify --+--> integrate one at a time
   |--> worktree C --> worker --> verify --+    (re-verify before each merge)
```

It runs a bounded worker pool and serializes verified integration. It uses no
manager model and invents no task graph. With `swarm --continuous`, the provider
CLI supplies one planning pass only after grounded work runs out, in another
isolated worktree, editing only the bounded `docs/STATUS.md` Next list. looptight
validates task shape, evidence paths, and the verifier before merging the plan
and starting another round.

## Repository coordinator

Many sessions can share one repository safely:

```text
many sessions --> shared task queue --> isolated worktrees --> verify --> merge one at a time
```

A repository-private SQLite database (`<git-common-dir>/looptight/coordinator.db`,
WAL mode) holds run identity, short transactional **task leases** fenced by
generation, proposal deduplication, and durable integration and publication
queues (`coordinator.py`). Planning and worker execution stay parallel. Only Git
integration serializes, behind a repository-private advisory lock guarding one
coordinator-owned **detached** integration worktree (`integration_queue.py`).
User worktrees are never reset or removed, and nothing force-pushes.

Each verified worker enqueues a fenced integration. The `Integrator` drains the
queue oldest-first under the lock, merging in the coordinator worktree,
verifying, and advancing the target ref by compare-and-swap. Every merge carries
a `Looptight-Integration-ID` trailer, so `reconcile()` resolves any integration
left mid-flight by a crash to exactly one reachable result. Publication is
separate and equally idempotent: it fetches first and finalizes without a second
push when the remote already has the result, pushing only the exact result SHA.

Coordination is **local to one machine and filesystem**. Activation is explicit:
`looptight migrate` (`Coordinator.open(activate=True)` then `activate_from_legacy`)
refuses while any legacy file claim is still live, then writes a
`coordinator-format.json` marker, after which legacy file claims fail closed. It
is idempotent and errors outside Git. Existing `next` / `status` / `swarm` JSON
keys are unchanged; coordinator counts are projected **additively** as a
`coordinator` block on `status`. The integration lock has a bounded timeout, and
failed or conflicting work is retained for recovery.

## Idea generation

A self-improvement loop should not stop the moment the grounded queue empties. By
default both queue-driven loops generate new evidence-backed tasks instead:

- **Session-native loop:** when `next` finds no grounded work it returns
  `no_work` with a `generate_ideas` directive (the shared `prompts.PLANNING_GOAL`).
  The installed instructions tell the **host session agent** to write 1 to 6
  grounded `## Next` tasks and continue. looptight makes no model call; the host
  session, already running, does the thinking, which preserves the no-calls
  contract.
- **`swarm --continuous`:** the deterministic orchestrator invokes the **planner
  subagent** when work is exhausted.

`ranking.py` weights human and planner-curated sources (`task-file`,
`status-next`) above automated signals (`lint`, `todo`), so generated and curated
intent is claimed before incidental nits. Generation is bounded by the planner
prompt's grounding rail (no evidence, no task), so the loop still terminates
honestly. `--no-ideas` or `idea_generation = false` restores stop-on-empty
everywhere.

A generated `## Next` task is also gated on its evidence. `from_status_next`
(`discovery.py`) drops an item whose `Evidence:` anchor names a file that does not
exist, using `grounding.py`, so a fabricated reference cannot enter the queue.
Items that name no anchor are left alone, so hand-written lists keep working.
`idea_eval.py` scores a generated batch on the same grounding plus area spread and
intra-batch distinctness, and `propose --eval` reports it for the live queue.

## Goal mode

`goal.py` runs the vision-driven build loop, the counterpart to evidence-first
`next`. It stores a goal (`vision`, optional `done_check`, `continuous`,
`max_iterations`, `iteration`) in repo-private state beside the coordinator, then
`goal next` decides the next step without a model call: stop at the iteration cap,
report done when the `done_check` command exits zero, or emit one build directive
(`prompts.GOAL_BUILD`, filled with the vision) and advance the iteration. The host
session builds each increment and `verify` gates the commit, so the verifier is the
trust anchor even though the direction comes from the vision rather than repo
signals. `goal check` exits zero when the done command passes, which lets a native
loop driver such as `/loop until: looptight goal check` run the loop hands-off.

### Metacognitive monitor and control (Phase 2)

A lightweight monitor, self-model, and control layer lets looptight learn from
past idea outcomes without storing state outside the repository or the
coordinator.

**Idea identity.** `idea_identity.py` computes a deliberately lossy 12-hex
identity for each candidate (`idea_id`). It is stable across line moves and minor
title rewording while keeping genuinely different ideas distinct. The write path
(recording outcomes) and the read path (building the self-model) use the same
function, so the two cannot drift.

**Outcome recording.** A `landed` outcome is recorded as a
`Looptight-Outcome: <idea_id> landed` git trailer on the integration commit
(`integration_queue.py`), verified structurally: only commits reachable from the
target ref are scanned, so a trailer on an unmerged branch never counts. A
`failed` outcome is recorded locally in the coordinator's `experience` table
(`coordinator.py`) and is never pushed.

That asymmetry is deliberate. Positive learning (what worked) is shared through
git history and is structurally verifiable by any session. Negative learning
(what failed recently) stays local to one machine: it guides the current session
without risking incorrect suppression elsewhere or polluting shared history.

**Self-model.** `experience.py` builds an in-memory `Model` by unioning
verified-landed counts (from git log) with recent local failures (from the
coordinator). The model carries per-idea counts and per-category aggregates. It
is advisory: callers fall back to default behavior when the model is empty or the
coordinator is unavailable.

**Advisory control.** Three mechanisms apply the model without ever overriding
the verifier:

- `propose.py` suppresses candidates whose idea has hit the cooldown failure
  threshold (configurable, default 2 recent failures within 24 hours).
- `ranking.py` scales each source's base weight by a clamped category yield
  factor (floor 0.5, ceiling 1.08) from landed and failed counts, so a boosted
  automated source stays below the next curated tier.
- `prompts.py` injects a bounded experience note (top failing and landing idea
  IDs) before the grounding rail when building the planning prompt, used by both
  the swarm planner and the session-native directive.

**Grounding and generation quality.** A second layer keeps generated work honest
and measurable:

- `grounding.py` resolves a task's `Evidence:` anchors against the working tree.
  `from_status_next` (`discovery.py`) drops a generated `## Next` item whose evidence
  does not point at a real file, so a fabricated reference cannot enter the queue;
  unanchored items are left alone, so hand-written lists keep working.
- `idea_eval.py` scores a generated batch on groundedness, area flexibility, and
  intra-batch distinctness. `propose --eval` reports it on demand, `status` carries
  an additive `idea_quality` block, and the `no_work` directive carries a
  `current_quality` feedback signal, so the loop can see how its generation lands.
- Failure attribution: the coordinator records *why* a task failed (conflict, test
  failure, timeout) alongside the category, and the planner note can name the
  dominant failure mode so the host avoids it, not just an opaque idea ID.

Deferred items (churn detection, shared negative learning, session-native writes,
and EVOC-style value-aware scoring) are documented in `docs/SPEC.md`.

## Usage-limit resume

Provider-native usage limits stay authoritative (see `SPEC.md`): looptight never
counts tokens or tracks billing. With the opt-in `--resume-on-limit`, the
deterministic orchestrator recognizes a usage or rate limit the provider reported
in its own output (`limits.py`), then waits and resumes instead of stopping. It
prefers the reset interval the provider named and otherwise backs off
exponentially, capping any single wait so a long reset is handled by re-polling.
The swarm applies this between rounds; the single-agent loop applies it between
iterations, where a wait costs no iteration-cap slot. Real verification failures
and crashes still stop the run.

## Validation order

1. Validate configuration and task evidence.
2. Atomically claim the task when Git-private state is available.
3. Let the native agent implement it.
4. Require the verifier to execute normally.
5. Treat only exit zero as a pass.
6. Review the diff and commit; remove the completed item from the bounded plan.

Heuristics can rank tasks or spot stalled progress. They cannot grant a passing
verdict.

## Adding an agent

Adapters are the only place that names a specific agent, so adding support for a
new one should not touch the loop. To add an agent:

1. Add an adapter under `src/looptight/adapters/` that knows how to launch that
   provider's CLI (the headless "supply" path) and, ideally, how to drive its
   native in-session loop.
2. Expose detection so `looptight doctor` reports the agent, its verify command,
   and whether the adapter is available and installed.
3. If the agent reads a project instruction file, teach `integration.py` to
   install the same bounded loop block (as it does for `AGENTS.md` and
   `CLAUDE.md` today).

Keep the adapter thin: it adapts the protocol to one CLI and holds no product
logic. PRs that add an adapter, especially one that drives a native loop, are
very welcome. See [CONTRIBUTING](../CONTRIBUTING.md).
