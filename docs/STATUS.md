# Self-improvement status

This is looptight's bounded running plan. Keep only the current objective,
validated results, and at most six executable tasks. Git history is the archive.

## Objective

Make looptight the smallest reliable validation and task protocol shared by
Codex, Claude Code, and OpenCode. The default path runs inside the user's
existing CLI session and makes no model or API calls of its own.

## Loop

1. Plan from repository evidence and user-facing friction.
2. Keep small tasks with observable acceptance conditions under `Next`.
3. Execute the highest-value task in the current agent session.
4. Require `looptight verify --json` to return `pass`.
5. Commit and push the coherent result, then update this file.
6. Stop successfully when `looptight next` returns `NO_WORK`.

## Validated

- `verify --json` schema v1 distinguishes pass, fail, timeout, and error.
- `next --json` schema v1 returns one grounded task or `NO_WORK`.
- Both protocols are provider-neutral and make no agent or network calls.
- Atomic task claims are shared privately across Git worktrees, recover after
  24 hours, and disappear when their source task is no longer grounded.
- `init --integrate` installs the same bounded session loop for Codex and
  OpenCode (`AGENTS.md`) and Claude Code (`CLAUDE.md`) without child agents.
- `status --json` reports validation readiness, workspace safety, claims, and
  the next action without running checks or changing state.
- `run` requires explicit `--headless`; deprecated `improve` no longer launches
  agents. Current-session docs make no provider-billing promises.
- Generated reflection, local cost gating, and the duplicate autonomous
  orchestrator are removed; legacy flags and `improve` return migration guidance.
- The runtime is standard-library-only; plain human output and versioned JSON
  require no Rich/Markdown dependency chain.
- Runtime contracts, summaries, adapters, and CLI contain no lesson or cost
  telemetry fields; deprecated TOML keys are safely ignored.
- Queued tasks require nonempty source evidence and an explicit observable
  acceptance condition before `next` can claim them.
- Command handlers are separated from the machine-facing protocol; the stable
  CLI surface is unchanged, `commands.py` remains below 250 lines, and its
  `__all__` exports only public command handlers.
- Proposal discovery (`discovery.py`) and ranking (`ranking.py`) are separate
  single-concern modules; `propose.py` only composes them, and `propose`/`next`
  JSON output is byte-for-byte unchanged.
- Status discovery enforces the documented six-task maximum while preserving
  executable task order.
- Package metadata and entry-point docs describe Looptight as a validation-gated
  task protocol, without learning, teaching, or autopilot claims.
- `next` rejects dirty Git worktrees before proposal or claim mutation, returns
  a machine-readable error with exit code 2, and remains unchanged outside Git.
- `next` reconciles claims against current task evidence even when the queue is
  empty, so completed work cannot leave contradictory active-claim status.
- Verifier shell launch codes 126/127 are execution `error` results with CLI
  exit 2; ordinary nonzero test verdicts remain `fail` with exit 1.
- Verifier timeouts terminate the spawned process tree before returning while
  retaining bounded partial stdout/stderr in the timeout result.
- Lint discovery uses only an already-installed `ruff` executable; it never
  invokes `uv`, installs packages, writes an environment, or accesses a network.
- Ruff discovery disables its cache, keeping `propose` free of repository state
  mutations while preserving the same lint candidates.
- Explicit `swarm --headless` uses a deterministic manager, distinct atomic
  claims, isolated worktrees, bounded concurrency, and serialized verified merges.
- Cross-worktree tests prove nonempty queues pass through `ClaimStore`; explicit
  task-selection control flow prevents duplicate workers from receiving one task.
- `swarm --json` emits a versioned schema with overall status, per-worker task
  IDs/status/errors/worktree paths, and the push outcome for automation.
- Human swarm output prints retained failed/conflicting worktree paths, and
  preparation errors remove only detached worktrees that never started a task.
- Provider invocations have an explicit wall-clock timeout that terminates the
  process tree and retains the worker worktree with a distinct timeout result.
- `ui` serves a dependency-free, read-only, loopback-only node graph from
  versioned Git-private swarm state with polling and restrictive browser headers.
- The graph supports pointer and keyboard node inspection plus read-only status
  filters; every projection redraws its dependency arrows without mutating state.
- Concurrent worker results publish in completion order for timely observation;
  verified integration and returned results remain ordered by worker number.
- Submitted workers publish a running state before result collection, so the UI
  distinguishes queued preparation from active provider execution.
- Atomic state publications include a backward-compatible UTC event timestamp;
  the UI reports its age without inferring provider health from elapsed time.
- Explicit continuous swarm mode repeats verified rounds and uses an isolated
  provider planning pass only when grounded work is exhausted; accepted plans
  are bounded, evidence-path validated, status-only, and verified twice.
- Planner evidence cannot cite the generated status file itself; rejected plans
  leave the invoking worktree clean and retain only their isolated worktree.
- Project configuration is limited to `verify`, explicit `tasks`, and
  `direct_main`; configured files feed grounded discovery and unattended runs
  refuse the primary worktree unless explicitly allowed.
- Swarm workers stage only task-attributable paths, and stable task fingerprints
  prevent equivalent discovery routes from relaunching completed work.
- Interrupting a swarm terminates registered provider process trees before the
  executor unwinds, preventing orphaned subscription-consuming workers.
- Remote mobile management has a security decision record: prefer provider-native
  control, otherwise require an identity-aware tunnel while retaining loopback.
- `Config` declares each field exactly once (`direct_main` deduplicated) under a
  frozen-dataclass round-trip test; ranking weights place configured `task-file`
  candidates above ad-hoc `todo` and `status-next` signals.
- `install_session_instructions` tolerates a START marker without END, `parse_score`
  is typed for optional output, and `Checkpointer.diffstat` returns empty on git
  failure — each covered by a regression test.
- The read-only dashboard shows an at-a-glance status tally, `swarm` prints a
  one-line outcome count after per-worker lines, and `next` human output includes
  each task's acceptance condition — each covered by a test, JSON unchanged.
- The dashboard shows idle empty-state guidance, `status` prints the resolved
  verify command, and `swarm` prints a start banner naming workers/agent/verify
  before the silent run — each covered by a test, JSON output unchanged.
- `doctor` prints actionable hints when verify or an agent is missing, and the
  dashboard inspector re-resolves the selected node each poll so its detail stays
  live — each covered by a test.
- Diagnostic output is clearer: run summaries surface the actual error, the claude
  adapter names the return code on native non-zero exits, the continuation context
  marks truncated verify output, settings hook errors name the actual type, and
  Makefile `test:` detection ignores commented lines.
- The dashboard event age reads in hours and days past an hour, and `propose`
  human output groups candidates by source priority — each covered by a test,
  JSON output unchanged.
- `ClaimStore.select` treats a claim with a non-string `task_id` as stale instead
  of raising `TypeError`, covered by a regression test.
- `is_git_repo` and `is_git_primary_worktree` have direct coverage proving real
  repo/non-repo detection and the primary-vs-linked-worktree distinction, with no
  production code change.
- Usage-limit detection honors an absolute wall-clock reset ("resets at 3:00pm")
  relative to an injected current time, rolling to the next day when already past,
  and falls back to relative/back-off otherwise — covered by tests.
- Idea generation is the default on an empty queue: `next` returns `no_work` with a
  `generate_ideas` directive (shared `prompts.PLANNING_GOAL`) so the host session
  generates grounded tasks; `swarm --continuous` plans via its subagent. `--no-ideas`
  / `idea_generation = false` restores stop-on-empty. looptight makes no model call.
- Ranking places human-curated `task-file`/`status-next` above automated `lint`/
  `todo`; `next` task JSON no longer triplicates the task text (`goal` is the
  summary, `evidence` the pointers, `acceptance` separate). Each covered by tests.
- The native delegate loop (`run --native`) shares the supply loop's usage-limit
  resume via a common `_with_limit_resume` wrapper: a provider limit during a
  driven loop waits (capped) and retries instead of stopping. Off by default;
  covered by tests, supply-loop behavior unchanged.
- Consecutive usage-limit resumes are boundable (`limit_max_resumes`, 0 = unbounded
  default) in both the single loop and the continuous swarm, so a perpetual limit
  signal stops with a clear error instead of looping forever. Covered by tests.
- `owner_id` (env override and default identity) and config.py's `find_config` and
  `render_config` now have direct unit coverage.
- Continuous swarm can wait out a provider-reported usage/rate limit and resume
  (`--resume-on-limit`, off by default): a shared adapter failure helper classifies
  the limit, back-off prefers the provider's named reset and is capped so the loop
  re-polls a long reset instead of sleeping unbounded. No token or billing tracking;
  `limits.py` is pure stdlib. Each piece covered by a test, default behavior unchanged.
- The single-agent headless loop (`run --headless --resume-on-limit`) waits out a
  provider usage limit between iterations without consuming an iteration-cap slot,
  sharing `limits.limit_wait`; swarm and single-round behavior unchanged. Covered by
  tests. The orchestrator topology and unattended recipe are documented in
  `docs/architecture.md` and `README.md`.

## Next

1. Add direct unit coverage for `_summary_and_evidence` task-field trimming.
   Evidence: src/looptight/tasks.py:40;
   Acceptance: new tests prove an `Evidence:`-bearing candidate yields a summary
   with the refs stripped out and the full (multi-ref) `Evidence:` string
   preserved, and an `Evidence:`-less candidate falls back to its detail line,
   with no production change, and the suite passes.

2. Document the optional `directive` field of `next` in the SPEC output contract.
   Evidence: docs/SPEC.md:178;
   Acceptance: the output-contract section states that `next` may include a
   `directive` (`generate_ideas`) on `no_work` when idea generation is enabled,
   doc-only, and the suite still passes.

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
