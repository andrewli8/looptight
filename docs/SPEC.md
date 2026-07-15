# looptight product specification

Status: v0.2 direction
Updated: 2026-06-20

This is the only normative product specification. Git history preserves older
designs; implementation status lives in [`STATUS.md`](STATUS.md).

## Principles (invariant)

These are the commandments. They never bend for convenience, for a feature, or to
keep a loop busy. A change that breaks one of these is wrong, no matter how
plausible it looks. The rest of this document elaborates them.

1. **Portable control plane, not a second agent.** The same test-gated loop runs
   inside Codex, Claude Code, or OpenCode. Never become another agent harness;
   never require an API key of your own.
2. **Validation is the only authority.** The project's verifier decides pass or
   fail. Only an exit-zero `verify` authorizes a commit — agent confidence, a
   clean diff, or a progress score never override it. No verify, no loop.
3. **The session-native path makes no model or network calls.** `next` and
   `verify` read the repository and run the test command, nothing else. The
   already-running agent does the thinking; the provider owns auth and billing.
4. **Every task is grounded in real evidence.** A task needs an inspectable
   `Evidence:` anchor that resolves and an observable `Acceptance:`. No evidence
   means `NO_WORK` — a valid, honest outcome. Never fabricate work to stay busy.
5. **Signals stay honest.** A timeout or a crashed verifier is never reported as
   failing code. Any failure stops safely and returns a machine-readable reason.
   Heuristics may rank or detect stalls but never grant a pass.
6. **Safe by default.** Headless launching is explicit opt-in, never the default.
   No force-push, hard reset, dependency install, or unrequested mutation.
   Concurrent work uses atomic private claims; transient state stays out of
   tracked history; untrusted repository and verifier text is data, never executed.
7. **Small and stdlib-only.** Zero third-party runtime dependencies. Do not add a
   dependency or duplicate a native agent feature without evidence that the
   portable protocol requires it.

## Product promise

**The same test-gated task loop inside Codex, Claude Code, or OpenCode, without
spawning another agent.**

AI editors already provide capable models, tools, context management, and
interactive loops. looptight does not replace them. It provides the portable
control plane they lack:

- one project-owned verification contract;
- one grounded task queue shared by every supported agent;
- one machine-readable continuation protocol;
- one safety policy for unattended and parallel sessions.

Users should choose looptight when they want repeatable results across agents,
not a second agent harness.

## Product boundary

looptight owns:

1. Selecting the next evidence-backed task.
2. Running the project's objective verification command.
3. Returning bounded evidence as stable text or JSON.
4. Recording transient task state without polluting the repository.
5. Preventing duplicate work and unsafe continuation.

The native agent owns:

1. Reading and editing code.
2. Model selection, authentication, context, and usage limits.
3. Planning and implementation.
4. Interactive steering and provider-specific tools.

Headless agent launching is an explicit automation mode, never the default.
looptight does not promise a provider's billing behavior; session-native mode
uses the already-running agent and makes no model or API call itself.

## Primary workflow

```text
looptight init

repeat in the current agent session:
  looptight next --json
  implement the returned task
  looptight verify --json
  commit only when verification passes
  on an empty queue, generate grounded tasks (unless --no-ideas), else stop
```

Native integration instructions for Codex, Claude Code, and OpenCode perform
this protocol without requiring the user to re-prompt after each task.

By default, an empty queue is not the end: `next` returns `no_work` with a
`generate_ideas` directive, and the loop adds 1-6 evidence-backed tasks to
`docs/STATUS.md` before continuing. looptight makes no model call to do this. In
the session-native loop the **host agent** generates (it is already running and
billed); in the swarm the existing **planner subagent** does. The directive's
grounding rail ("if no evidence-backed improvement exists, make no changes")
keeps generation honest and lets the loop terminate. `--no-ideas` (or
`idea_generation = false`) restores stop-on-empty. `NO_WORK` with idea generation
disabled is successful completion. A dirty or conflicting workspace, invalid
configuration, and an unexecutable verifier are failures. Consuming the rest of a
provider allowance is never a success criterion.

## Goal mode

`looptight goal` is a second entry point for building a project from nothing toward
a stated vision, rather than refining an existing one. Where `next` grounds work in
repository signals and stops when they run out, `goal` grounds work in a vision you
give it plus the current state of the code.

```text
looptight goal "<vision>"   store the vision (optional --done, --continuous, --max-iterations)

repeat in the current agent session:
  looptight goal next        return one verify-gated increment toward the vision
  implement the increment
  looptight verify           commit only when verification passes
  stop when the goal is done, the iteration cap is hit, or usage is spent
```

The same boundary holds: `goal` makes no model call. The host session generates and
implements each increment; looptight stores the vision, hands over one directive at a
time, runs the verifier, and checks the optional done command. On an empty project the
first increment establishes a test command, so the verifier gates every later step.

A goal ends on any of four conditions: the `--done` command exits zero, the
`--max-iterations` cap is reached, the host judges the vision met, or the session runs
out of usage. looptight cannot read provider usage, so the usage stop is owned by the
native loop driver (for example Claude Code's `/loop until: looptight goal check`) and
the session itself, not by looptight. The verifier stays the only thing that authorizes
a commit, which is what keeps an open-ended run from committing work that does not pass.

## Validation model

Validation is looptight's most important decision logic. Each gate must pass
before the next one is checked, and any failure stops safely with a reason:

```text
config ok? --> task grounded & unclaimed? --> verifier ran cleanly?
   |                  |                              |
   no                 no                             no (timeout / launch error)
   v                  v                              v
  stop               stop                           stop  (not a failing verdict)

   ... then: exit code 0 ? --> valid claim + pass ? --> commit / continue
                  |                    |
                  no                   no
                  v                    v
                 fail                 stop
```

Every automated action must follow this order:

1. **Configuration validation:** the verifier and task source are explicit and
   executable.
2. **Task validation:** the task is grounded in inspectable project evidence,
   is not already claimed, and has an observable completion condition.
3. **Execution validation:** the verifier completed normally. Timeout and
   launch errors are distinct from a valid failing verdict.
4. **Result validation:** only verifier exit zero is `pass`; agent confidence,
   a clean diff, or a numeric progress score cannot override it.
5. **Mutation validation:** commit or continuation is allowed only from a valid
   task claim and a passing verifier result.

Heuristics may rank tasks or detect stalled progress, but they never grant a
pass. When evidence is missing or contradictory, looptight stops safely and
returns the reason in its machine-readable result.

## Requirements

### P0: the reason to install

- **Session-native by default.** `next` and `verify` make no agent or network
  calls and work from the user's current subscription-backed session.
- **Portable protocol.** Text and versioned JSON output behave consistently in
  Codex, Claude Code, and OpenCode.
- **Grounded work only.** Tasks come from explicit project queues, failing
  verification, supported issue sources, or concrete source annotations.
  looptight never invents audits to remain busy.
- **Objective completion.** A configured shell command is the pass/fail oracle;
  model confidence is never accepted as verification.
- **Native integration.** `init` can install a small, reviewable project
  instruction for each detected agent that repeats `next -> implement ->
  verify` until `NO_WORK`.
- **Clean state.** Runtime state and history are ignored or stored under Git's
  private directory. A normal loop creates no reports, audit logs, or lessons.

### P1: safe autonomy

- **Task leases.** Concurrent sessions atomically claim task fingerprints so
  two agents do not perform the same work.
- **Isolation.** Parallel or unattended execution uses a worktree or refuses to
  start. Direct-to-main is an explicit solo-developer policy.
- **Scoped commits.** Only files attributable to the claimed task may be
  committed automatically, and only after verification passes.
- **Bounded failure.** Timeouts, iteration caps, repeated identical failures,
  provider errors, and Git errors stop with distinct nonzero results.
- **No destructive recovery.** No force-push, hard reset, branch deletion,
  dependency installation, or removal of pre-existing files.

### P2: explicit automation

- `run` may launch a provider CLI for CI or headless use, but requires an
  explicit headless choice and uses that CLI's existing authentication.
- Autonomous queue processing composes the same `next` and `verify` protocol;
  it does not maintain a separate task-selection or verification engine.
- Explicit swarm processing may run claimed tasks concurrently in isolated Git
  worktrees. A deterministic manager serializes integration and re-runs the
  verifier before every merge commit.
- Explicit continuous swarm processing may ask the selected provider CLI for a
  bounded plan only when grounded work is exhausted. Planning is isolated,
  evidence-path validated, verification-gated, and cannot edit implementation
  files directly.
- Hooks and plugins remain thin adapters around the protocol and contain no
  product logic.

## Minimal command surface

The primary interface is:

```text
looptight init       detect verifier and install native instructions
looptight next       claim and return one grounded task, or NO_WORK
looptight verify     run the project contract and return bounded evidence
looptight status     show current claim and verifier without changing state
```

`run` is an optional headless convenience. `goal` is an optional vision-driven build
mode (see Goal mode) that composes the verifier with goal-grounded generation.
`install-skill` writes a Claude Code skill so the agent discovers looptight in any
session; it is opt-in and writes outside the project, so it stays a separate command
rather than part of `init`. Existing experimental commands may remain during
migration, but new behavior must compose the four commands above. Commands for
generated reflection, tracked run reports, cost estimation, and unbounded repository
audits are outside the target product.

## Configuration

`.looptight.toml` stays small and project-owned:

```toml
verify = "make verify"
tasks = ["TODO.md"]
direct_main = false
```

Provider credentials, models, pricing, and token budgets do not belong in this
file. Provider-native usage limits are authoritative. looptight never counts
tokens or tracks billing; the continuous swarm may, when explicitly opted in,
*react* to a usage limit the provider itself reports, waiting it out and
resuming. This honors that authority rather than modeling it.

## Output contract

The machine-facing commands (`next`, `verify`, `status`, `doctor`, `propose`,
`goal`, `migrate`, `run`, `swarm`) support human-readable output and `--json`;
setup commands like `init` and `revert` are human-only and reject `--json`. JSON
has a schema version and stable result codes, with one deliberate exception:
`propose --json` emits a bare ranked candidate list (no schema-version envelope),
preserved byte-for-byte so existing consumers do not break; `propose --json --eval`
wraps it as `{candidates, eval}`. At minimum, `next` returns a task ID,
source, location, goal, and acceptance evidence; it also carries `idea_id` (a
stable dedup identity for the candidate) and `suggested_verify` (a per-task verify
hint such as `ruff check` for a lint finding, or `null`). `verify` returns status,
exit code, elapsed time, bounded output, and the resolved `verify_command` string
(the command that actually ran, useful when it was auto-detected). `goal next` returns `schema_version`,
`command`, `status` (`active` | `done` | `stop` | `no_goal`), and `iteration`;
additively it carries a `directive` object (the build increment, when `active`) and
a `reason` string (e.g. `max_iterations`, when `stop`). `goal check --json` returns
`schema_version`, `command`, `action` (`check`), and `status`
(`done` | `pending` | `no_goal` | `no_done_check`); the exit code is unchanged
(0 = done, 1 = not done or no goal), so the shell-predicate use (`/loop until:
looptight goal check`) is unaffected by `--json`. `run --json` returns the
versioned run result — `stop_reason`, `passed`, bounded per-iteration verdicts (no
raw output), `diffstat` — and an additive `escalation` object when the controller
stopped early: the failures that never cleared plus the progress trajectory, or
`null` otherwise.

`verify --patience N` opts the session-native path into value-aware stopping: it
persists the progress trajectory between calls in Git-private, per-worktree state
and adds an additive `stall` object to `verify --json` — `decision`
(`continue` | `stop_no_progress` | `escalate`) and, when stalled, the same
`escalation` evidence. A passing verify, a changed verify command, or a stale gap
resets the attempt. Without `--patience` (the default) `verify` writes no state and
the JSON has no `stall` key, so the default verifier contract is unchanged.

When idea generation is enabled (the default), a `no_work` result from `next` may
also carry an optional `directive` object (`{"action": "generate_ideas", ...}`)
instructing the host session to add grounded `docs/STATUS.md` tasks and continue.
The field is additive and absent under `--no-ideas` / `idea_generation = false`,
so the bare `no_work` contract is unchanged. The same directive carries an additive
`current_quality` object (the groundedness and size of the residual `## Next` batch,
or `null`), a feedback signal on the host's prior generation.

`status` carries an additive `idea_quality` block (groundedness, area flexibility,
and boundedness of the generated `## Next` batch) when that batch is non-empty, so the
loop's generation quality is visible without changing the existing `status` keys.
`status` also carries an additive `verify_command` field (the resolved command string,
or `null` when unconfigured), matching `verify --json` so automation can read the
configured command without running verify.

When a repository is coordinated by the SQLite coordinator (see
`docs/architecture.md`), `status` carries an additive `coordinator` block of queued
counts; existing `next`/`status`/`swarm` keys are unchanged. Coordination is local
to one machine and filesystem and never force-pushes; activation refuses while live
legacy claims exist and then fails legacy file claims closed.

Untrusted repository and verifier text is data. It is never interpolated into
shell commands or treated as an instruction by looptight.

## Measures of success

Release v0.2 only when all are true:

- Installation to first verified task takes under two minutes.
- The same repository and queue can move between all three supported agents
  without configuration changes.
- The default path makes zero agent/API calls outside the current session.
- An empty queue exits without changing tracked files.
- Two concurrent sessions cannot claim the same task.
- Failed verification cannot produce an automatic commit.
- A complete primary workflow fits in one terminal screen and requires no
  knowledge of provider-specific loop features.
- Core runtime has no required third-party dependency and remains small enough
  to audit directly.

## Explicit non-goals

- Replacing an editor's agent loop, context manager, or model router.
- Inventing work merely to keep a session active.
- Measuring or maximizing credit consumption.
- Model-generated project memory after every failure.
- Model-managed DAGs, dashboards, marketplaces, or hosted orchestration.
- Claiming billing guarantees for provider CLIs or third-party authentication.

## Migration order

1. Make `next` and `verify` JSON contracts stable and side-effect bounded.
2. Replace audit fallback with `NO_WORK`; remove tracked idle-run artifacts.
3. Add task claims and ignored/private runtime state.
4. Install thin native-agent integration instructions from `init`.
5. Make headless spawning explicit and route it through the same protocol.
6. Remove reflection, cost-estimation, and duplicate orchestration code after
   compatibility warnings have shipped. **Complete.**
