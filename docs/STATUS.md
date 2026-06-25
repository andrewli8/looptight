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
- `_summary_and_evidence` has direct coverage proving inline `Evidence:` refs are
  split out of the summary (single and multi-ref) and that marker-less candidates
  fall back to their detail line, with no production change.
- The SPEC output contract documents the optional `next` `directive` field
  (`generate_ideas` on `no_work`), additive and absent under `--no-ideas`.
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
- Interrupting a swarm now publishes terminal `interrupted` manager and active-worker
  state after stopping owned provider processes, so the read-only dashboard does not
  retain a historical `running` state. Covered by a regression test.
- Successful worker-worktree removal now also removes its empty per-run swarm
  directory; no-work and completed rounds leave no directory litter, while failed
  workers retain their recovery worktrees. Covered by swarm regression tests.
- CLI parsing directly covers non-positive swarm worker counts and provider
  timeouts, returning argparse exit code 2 with no production-code change.
- Usage-limit parsing directly covers out-of-range absolute reset times, which
  remain classified as limits without inventing a retry interval.
- A repository-private SQLite coordinator foundation now initializes schema v1
  transactionally under Git's common directory with WAL, foreign keys, uniqueness
  constraints, bounded busy handling, repository isolation, and rollback coverage.
- Coordinator task leases: unique run IDs and fenced SQLite leases whose generation
  rejects renewal/completion by stale owners; `next`/`status` route through the
  coordinator with unchanged JSON; ten same-directory processes claim distinct tasks.
- Repository integration serializes behind an advisory lock over one coordinator-owned
  detached worktree per target ref; user worktrees are never touched; cross-process
  exclusion and worktree validation are covered.
- Verified swarm branches drain through a durable FIFO integration queue (fenced
  enqueue, oldest-first under the lock, CAS ref advance, atomic terminal lease/task
  transitions); stale fences are superseded; swarm JSON unchanged.
- Integration crash recovery is idempotent via `Looptight-Integration-ID` trailers
  (`reconcile` yields exactly one reachable result across every boundary); publication
  is separate, fetches first, finalizes without a second push, and never force-pushes.
- Concurrent planners deduplicate equivalent proposals; `status` projects coordinator
  counts additively; activation fails closed against live legacy claims (marker written
  last); the WAL first-open race is retried. A 10-process acceptance suite is covered.
- `looptight migrate` activates the repository coordinator from the CLI: writes the
  marker, refuses (exit 2) while live legacy claims exist, errors outside Git, is
  idempotent, and emits `--json` — covered by tests, other command JSON unchanged.
- `run_swarm` reconciles any integration left `integrating` by a crashed prior run
  before claiming new work (`_reconcile_pending` → `Integrator.reconcile`), so a crash
  finalizes to exactly one reachable result — covered by an after-commit crash test.
- `swarm --push` publishes merged integrations through the durable `Publisher`
  (`_publish_via_queue`): fetch-first, exact-SHA, no force, idempotent — covered by an
  end-to-end test against a bare remote; the legacy direct push remains a fallback.
- `looptight migrate` and coordinator activation are documented in README and
  architecture (activation, fail-closed, idempotent, outside-Git error).
- `finish_integration` conflict path has direct coverage: the fenced lease is released
  and the task requeues while attempts are below the cap, then fails at the cap and is
  no longer claimable.
- Coordinator runs carry a usable heartbeat: `heartbeat` refreshes an active run and
  `reap_abandoned` marks runs whose heartbeat predates a deadline `abandoned` and frees
  their leases (tasks requeued) before TTL — covered by a time-injected test.
- The session `next` path reaps abandoned-run leases instead of stalling for a full
  lease TTL: it heartbeats its own run, then reaps runs idle past a 10-minute deadline
  before claiming, so a leaked lease from a one-shot `next` that claimed and exited is
  reclaimed quickly while a live looping session keeps its own lease. Integration
  fencing is unchanged. Covered by reclaim and live-lease-spared tests in test_tasks.py.
- `status` human output prints the coordinator queued task/integration/publication
  counts when the repository is coordinated; JSON output unchanged. Covered by a test.
- The publication push-rejected path is covered: a rejected push attempts only the
  exact result SHA once (no force, no candidate replay) and leaves the publication
  `failed`.
- The integration merge-conflict path is covered: a conflicting candidate aborts the
  merge, returns a `conflict` outcome with a retained worktree, and releases the
  fenced lease.
- `Integrator._run` raises a clear `ValueError` (not a `-O`-strippable `assert`) when
  a non-superseded record is integrated without `root`/`verify` — review concern C7,
  covered by a test.
- Worker timeouts are classified by provider exit code 124 (`IterationResult`/
  `RunResult` carry `returncode`), not by matching a base.py error string — so a
  reworded timeout message still tags `timeout`. Review concern; covered by a test.
- `run_continuous_swarm` stops after `max_idle_rounds` (default 3) consecutive
  planning rounds with no merged progress, so a planner that keeps planning without
  yielding claimable work cannot loop forever under `--max-rounds 0`. Review concern;
  covered by a test; normal progress resets the counter.
- looptight's automated git commits/merges (integration queue and swarm) use a
  deterministic `looptight` committer identity, so integration succeeds where no
  ambient git identity is configured (CI, fresh containers) — fixes the CI build
  failure; covered by an identity regression test.
- `run`/`swarm` accept `--model` (config `model`), threaded to the provider so
  spawned sessions use a chosen model (e.g. `--model opus`); the claude adapter's
  existing `--model` plumbing carries it. Covered by loop and parser tests.
- The deterministic `_GIT_IDENTITY` committer tuple for looptight's automated
  commits/merges is defined once in `integration_queue.py` and imported by
  `swarm.py`, so the two cannot drift; behavior and tests unchanged.
- `test_swarm_publishes_worker_results_in_completion_order` asserts the
  per-completion partial publish (one worker `verified` while the other is
  `running`) order-independently, so it no longer flakes on thread-scheduling
  variance; the guarantee (state published per completion, not once at the end)
  is unchanged and the production code is untouched.
- `ClaudeAdapter.drive_native_loop` now classifies a usage/rate limit on a
  non-zero native exit and carries the stable `provider rate limit reached`
  marker, so `run --native --resume-on-limit` can actually wait it out and retry;
  previously the only native-capable adapter returned `error=None`, leaving the
  documented delegate-loop resume unreachable in production. A non-limit failure
  keeps `error` unset (transcript surfaced, no spin). Covered by adapter tests.
- The skipped-test env-gate filter (`from_skipped_tests`) strips string literals
  before matching `_OPTIN_RE`, so a skip whose *reason* message merely mentions
  `environ`/`os.environ`/`os.getenv` is no longer mistaken for an opt-in env gate
  and silently dropped; genuine `skipif(not os.environ.get(...))` gates are still
  ignored. Fixes a discovery false negative; covered by two regression tests.
- `SwarmResult.reason` records why a continuous run returned (`ok`/`no_work`/`idle`/
  `limit`/`error`), additive to swarm JSON, so a supervisor classifies outcomes
  without parsing error strings. Covered by tests.
- `looptight daemon` supervises an unbounded continuous swarm forever: it reruns
  the swarm, looping immediately after merged progress, polling after `--idle-sleep`
  when idle, and backing off (capped, exponential) on faults; crashes are absorbed
  as faults and it stops gracefully on SIGTERM/SIGINT. It spends no allowance itself
  and turns the bounded loop into genuine 24/7 operation on a host that stays up.
  Stdlib-only (`daemon.py`); systemd unit + Dockerfile under `deploy/`; documented
  in `docs/daemon.md`. Covered by daemon and CLI tests.
- Idea identity: `idea_identity.py` computes a stable, deliberately lossy 12-hex
  `idea_id` per candidate. The identity is stable across line-number shifts and
  minor title rewording; the same function is used on both the write and read paths.
- Outcome recording: a `landed` outcome is a `Looptight-Outcome: <idea_id> landed`
  git trailer on the integration commit (verified by scanning commits reachable from
  the target ref only). A `failed` outcome is recorded locally in the coordinator
  `experience` table and never pushed. Positive learning is shared and structurally
  verifiable; negative learning is local.
- Self-model: `experience.py` builds an in-memory `Model` from verified-landed counts
  (git log) and recent local failures (coordinator). Per-idea and per-category
  aggregates; advisory only (callers degrade to defaults when the model is empty or
  unavailable).
- Advisory control: `propose.py` suppresses candidates at the failure cooldown
  threshold; `ranking.py` applies a clamped category-yield reweight (floor 0.5,
  ceiling 1.08) to source weights; `prompts.py` injects a bounded experience note
  before the grounding rail in the planning prompt. The verifier remains the sole
  authority on pass/fail.
- `status` reports an additive readiness object (`tier`, checks, and next
  remediation) plus matching human output, covering verify presence, Git
  cleanliness, coordinator activation, task-source health, and agent availability.
  Ready, partial, unsafe, and read-only status paths are covered by tests.
- `status` reports additive verifier-quality classification (`none`, `lint-only`,
  `unit`, `integration`, `e2e`, or `custom/unknown`) plus a plain risk note in
  human output. Missing verifier, pytest, ruff, npm test, and make test cases are
  covered without claiming semantic coverage.
- `status` reports additive concurrency safety (`safe`, `degraded`, `unsafe`)
  with local-filesystem scope, coordinator activation, legacy-claim, active-lease,
  integration-queue, and publication-queue checks plus remediation. Safe,
  degraded, unsafe, and v1-compatible JSON paths are covered by tests.
- Human `next`, `verify`, and `swarm` output now explains selected task evidence
  and acceptance, verifier result and changed files, serialized integration, and
  next safe action while preserving JSON contracts. Each path is covered by tests.
- `doctor` is documented as the non-mutating guided setup check and now reports
  coordinator state, setup readiness, and the exact next setup command without
  starting headless/swarm execution. Ready and not-ready paths are covered by
  no-write tests.
- Human `swarm` output now prints plain recovery guarantees for stale lease
  requeue, pending integration reconciliation, and rejected push handling while
  preserving the final outcome tally and JSON compatibility. Recovery messaging
  is covered by swarm CLI tests.
- Policy controls are parsed from `.looptight.toml`, rendered in default config,
  exposed additively on `status --json`, and fail closed for protected-path verify
  changes and `swarm --push` when direct pushes are disabled. Covered by CLI,
  swarm, and config tests.

- TODO/FIXME/HACK/XXX discovery spans JS/TS (`.js`, `.jsx`, `.ts`, `.tsx`,
  `.mjs`, `.cjs`) via a quote-aware comment scanner that ignores markers inside
  string/template literals, so polyglot repos get the same grounded signal; the
  Python `tokenize` path is unchanged. Covered by tests.

- Skipped-test discovery spans JS/TS (`it.skip`/`describe.skip`/`test.skip`/
  `test.todo`/`xit`/`xdescribe`) in `tests/`, matching markers on code with string
  literals stripped and comment lines ignored; pytest skip detection (env-gate
  opt-in, conditional guards) is unchanged. Covered by tests.

- JS/TS TODO and skipped-test discovery covers colocated tests anywhere
  (`*.test.*`, `*.spec.*`, `__tests__/`), not just `tests/`, pruning vendored
  and build dirs; Python and existing `tests/` behavior unchanged. Covered by tests.

- `doctor` reports a `coordination:` line (local-only SQLite coordinator / file
  claims / not activated) naming the single-machine boundary, and `status --json`
  carries an additive `coordination_scope` field, via a `coordination_scope`
  helper. Covered by tests across the three states.

- `daemon --on-fault CMD` runs CMD with a JSON fault payload (`cycle`, `reason`,
  `backoff_s`, `last_error`) on stdin when a cycle faults; the flag is optional
  (default no-op) and a failing hook never stops the daemon (guarded in both
  run_daemon and the exec). Covered by tests.

- The README has a Glossary defining its core jargon (verify, worktree, headless,
  claim, swarm, daemon) in one line each, with a pointer link from the intro, so
  a newcomer can decode the terms without leaving the page. Covered by a test.

- JS/TS TODO/FIXME discovery reads markers inside multi-line `/* ... */` block
  comments (the scanner tracks block state across lines), not only a block's
  opening line; single-line `//` and inline `/* */` behavior and string-literal
  guarding are unchanged. Covered by tests.

- docs/daemon.md documents the `--on-fault CMD` hook: its JSON payload fields
  (`cycle`, `reason`, `backoff_s`, `last_error`), that it is optional, and that a
  failing or slow hook never stops the daemon. Covered by a doc-accuracy test.

- The `src/` and `tests/` JS/TS file scan (`_files_with_exts`) prunes vendored and
  build directories (node_modules, .git, .venv, dist, build), so a marker under a
  `node_modules/` directory inside `src/` is not surfaced as noise; non-vendored
  files are unchanged. Covered by a test.

- The JS/TS skip detector ignores a skip marker mentioned in a trailing `//` or
  `/* */` comment on a code line (it strips comments as well as string literals
  before matching), so only real `it.skip`/`describe.skip`/`xit` calls are
  surfaced. Covered by a test.

- The README documents that TODO/FIXME and skipped-test discovery is polyglot:
  Python plus JS/TS (`.js`/`.ts`/`.tsx`), including colocated `*.test.*` files and
  `__tests__/` directories, with string/comment markers ignored and vendored dirs
  pruned. Covered by a doc-accuracy test.

- CI/local gate drift is guarded: a regression test asserts the daemon/agent CLI
  paths do not require a coding agent on PATH (providing `--agent` is enough),
  and CONTRIBUTING documents a CI-conditions run (no agent on PATH, no global git
  config). A global git-identity conftest fixture was intentionally NOT added: env
  GIT_COMMITTER_* overrides the integrator's `-c user.name=looptight` and breaks the
  deterministic-identity guarantee, and the suite already passes with no global config.

- CI pins non-deprecated GitHub Actions (`actions/checkout@v5`,
  `actions/setup-python@v6`), clearing the Node 20 deprecation warning. Confirmed
  green on both Python 3.11 and 3.12.

- `looptight status` renders a terminal panel of live swarm/daemon state (manager
  status, a worker tally by state, and per-worker number/status/task/error) from the
  Git-private swarm-state file via a pure `ui.render_state_panel`; empty when no
  workers; status JSON is unchanged. In-CLI visibility without a browser. Covered by tests.

- `looptight status --watch` live-refreshes the swarm/daemon panel on an interval
  (`--interval`, default 2s), re-reading state each tick until interrupted; the loop
  takes an injected sleep/tick-cap so it is testable without waiting. Stdlib only.
  Covered by a test that drives one render tick.

- Claim fingerprints for curated lists (`status-next`/`task-file`) drop the docs
  file's line number, so a re-queued task is not silently skipped when the line
  drifts as docs/STATUS.md grows. Root-caused from a stuck queue (every task row
  marked complete because each rewrite minted a new line-based fingerprint). Covered
  by a line-drift stability test; the cross-route stability test still holds.

- Experience reweighting is two-sided: the landed trailer records the task source
  (`<idea> landed <source>`), `build_model` populates `category_landed` from it via
  `landed_category_counts`, and `reweight_factor` boosts a high-yield category above
  1.0 (still clamped below curated tiers). The learning loop now lifts what pays off,
  not only damps failures. Covered by tests; backward-compatible trailer parsing.

- `looptight statusline` prints a one-line swarm summary (`looptight: 3 running ·
  1 merged`, or `looptight: idle`) for a status bar, reading Claude Code's status-line
  JSON on stdin defensively (picks the repo from `workspace.current_dir`/`cwd` else
  cwd) and never erroring; README documents the settings.json `statusLine` wiring.
  Covered by tests.
- README's runtime-dependency claim matches reality: the package declares zero runtime
  dependencies (`pyproject.toml` `dependencies = []`, stdlib `Console` replaced rich),
  and the README states there are no third-party runtime dependencies. Guarded by a
  doc-accuracy test that fails if `src/` imports rich or the stale claim returns.

- `looptight goal` adds a vision-driven build mode beside the evidence-first `next`
  loop: `goal "<vision>" [--done CMD] [--continuous] [--max-iterations N]` stores a
  repo-private goal; `goal next` emits one verify-gated build directive (bootstrapping
  a test command first on an empty repo), `goal check` exits 0 when the done-check
  passes (for `/loop until:` wrappers), `goal status`/`clear` manage it. No model
  calls; the host builds. An idempotent goal-loop block installs via `init
  --integrate`, and `--continuous` prints an agent-tailored hands-off driver recipe.
  Designed in docs/superpowers/specs/2026-06-24-looptight-goal-design.md; covered by
  tests in test_goal.py and a README doc test.
- A top-level `LICENSE` file ships the MIT license text with the copyright holder
  from pyproject's `authors`; guarded by a doc-accuracy test that checks both
  "MIT License" and the holder name.
- The CLI argparse type validators (`_positive_int`, `_port`) have direct unit
  tests asserting they reject zero/negative and out-of-range ports with
  `argparse.ArgumentTypeError`, so bad flags fail at parse time.
- `load_config` rejects a negative `max_changed_files` with a `ConfigError` that
  names the file and field, covered by a test in test_config.py.
- `load_config` rejects an empty string inside `protected_paths` with a
  `ConfigError` naming the file and field, covered by a test in test_config.py.
- `_parse_absolute_reset` treats `12:00am` as midnight (hour 0): from 11pm the
  next reset is one hour out, covered by a test in test_limits.py.
- `_truncate` keeps verifier output within `_MAX_OUTPUT_CHARS` by counting the
  head+tail separator against the budget, covered by a test in test_verify.py.
- `read_goal` returns `None` on a non-UTF-8 `goal.json` (the except widened to
  `ValueError`, covering `UnicodeDecodeError`), covered by a test in test_goal.py.
- `write_goal` removes its `.tmp` file if the write or atomic rename fails, so a
  failed save leaves no stale state behind, covered by a test in test_goal.py.
- The read-only view's `ui.read_state`/`write_state` got the same state-IO
  hardening as goal.py: a non-UTF-8 state file degrades to `empty_state()` (except
  widened to `ValueError`) and a failed atomic save unlinks its `.tmp`; covered by
  tests in test_ui.py.
- The CHANGELOG's `[Unreleased]` section records the post-0.1.0 user-facing
  changes and the 0.1.0 entry lists the `doctor` and `propose` commands; a doc
  test asserts both commands appear and `[Unreleased]` is non-empty.
- `next`'s human error output explains a dirty worktree and suggests commit/stash
  instead of echoing the bare `ERROR: dirty_worktree` code, covered by a test in
  test_cli.py.
- SPEC's output contract documents the always-present `idea_id` and
  `suggested_verify` task fields, guarded by a doc test in test_docs.py.
- `_remove_worker_worktree` uses `git worktree remove --force` so a disposable
  worker worktree holding untracked files is removed rather than leaked on disk,
  covered by a test in test_swarm.py.
- `detect_verify`'s Makefile branch tolerates a non-UTF-8 file (except widened to
  `(OSError, ValueError)`, matching the package.json branch) instead of crashing
  `init`/`doctor`, covered by a test in test_detect.py.
- `init --integrate` reads all managed-block targets up front and raises a clear
  `ConfigError` on a non-UTF-8 `CLAUDE.md`/`AGENTS.md` (instead of a raw traceback
  or a partial write), covered by a test in test_integration.py.

## Next

_None pending. The loop generates evidence-backed tasks here when this drains._

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
