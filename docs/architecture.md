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
