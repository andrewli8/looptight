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

## Next

1. Include the actual error message in the run summary: when a `RunResult` stops
   with reason ERROR, `render` currently shows only "stopped: error" and drops
   `result.error`, leaving no context. Surface the error text.
   Evidence: src/looptight/summary.py:28; Evidence: tests/test_summary.py:1;
   Acceptance: render of an ERROR result with a non-None error includes the error
   string, non-error summaries are unchanged, a new test in tests/test_summary.py
   asserts the message appears, and the suite passes.
2. Make the claude adapter's non-zero exit phrasing consistent: the native loop
   path reports "exited non-zero" while `run_iteration` reports "exited {code}".
   Align the native path to name the return code.
   Evidence: src/looptight/adapters/claude.py:75; Evidence: tests/test_adapters.py:1;
   Acceptance: both the supply and native paths report a non-zero exit with the
   return code in the message, a new test in tests/test_adapters.py asserts the
   native path includes the code, and the suite passes.
3. Mark truncated verify output in the continuation context: `_continuation_context`
   truncates to the last 3000 characters with no indication, so dropped early
   detail is invisible. Add a truncation marker when output exceeds the threshold.
   Evidence: src/looptight/loop.py:29; Evidence: tests/test_loop.py:1;
   Acceptance: output longer than the threshold includes a truncation marker while
   short output is passed through unchanged, a new test in tests/test_loop.py
   asserts both behaviors, and the suite passes.
4. Name the actual type in settings hook errors: "hooks is not an object; refusing
   to edit" should say what was found (for example a list) to make a malformed
   settings file debuggable.
   Evidence: src/looptight/settings.py:77; Evidence: tests/test_settings.py:1;
   Acceptance: the error message includes the actual JSON type when hooks is not an
   object, the valid-object path is unchanged, a new test in tests/test_settings.py
   asserts the type name appears, and the suite passes.
5. Harden Makefile `test:` detection so a genuine target is recognized and a
   commented `# test:` line is not mistaken for one, without changing detection for
   the cases already handled.
   Evidence: src/looptight/detect.py:19; Evidence: tests/test_detect.py:1;
   Acceptance: a new test in tests/test_detect.py proves a real `test:` target is
   detected and a commented `# test:` line is not, existing detection behavior is
   unchanged, and the suite passes.

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
