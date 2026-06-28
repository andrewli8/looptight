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
- `ranking.dedupe()` has direct unit tests proving that candidates differing only
  in title case/whitespace are deduplicated, distinct-location candidates are kept,
  `None` location is a valid deduplication key, and an empty input returns an empty
  list — each covered by new tests in `tests/test_propose.py`.
- `metacog._summarize()` has direct coverage for its three previously-untested
  branches: `total == 0` ("No specific failures parsed"), `persisted == False`
  ("Showing the latest … none held"), and `iterations == 1` ("1 try") — each
  asserted by a distinct test in `tests/test_metacog.py`, no production change.
- `grounding.ref_resolves()` trailing-period stripping (`rstrip(".")`) is covered
  by `test_ref_resolves_strips_trailing_period` in `tests/test_idea_eval.py`:
  a ref ending in `.` resolves when the file exists and fails when absent.

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
- `propose`'s candidate-count header pluralizes on count ("1 candidate task" vs
  "2 candidate tasks") instead of the lazy "task(s)", covered by a test in
  test_cli.py.
- JS skip discovery recognizes Jest's `xtest(` alias (added to `_JS_SKIP_RE` and
  `_JS_SKIP_NAME_RE`) alongside `xit`/`xdescribe`, covered by a test in
  test_propose.py.
- A corrupt claim with a non-numeric `claimed_at` is treated as expired (all three
  timestamp reads route through a `_claimed_at` helper that returns `0.0` on an
  unparseable value) rather than crashing `next`/`status`, covered by a test in
  test_claims.py.
- `settings.py` writes the user's `~/.claude/settings.json` atomically (temp +
  `os.replace`, unlinking the temp on failure), so an interrupted write cannot
  corrupt the user's Claude Code config, covered by a test in test_settings.py.
- `_install_block` writes `CLAUDE.md`/`AGENTS.md` atomically via `_atomic_write`,
  so an interrupted `init --integrate` cannot truncate a user's instructions file;
  all user-file write paths (goal/ui/settings/integration) now share the pattern.
  Covered by a test in test_integration.py.
- SPEC's Output contract documents the `goal next --json` fields (`schema_version`,
  `command`, `status`, `iteration`, additive `directive`/`reason`), guarded by a
  doc test in test_docs.py.
- `run_done_check` has direct unit coverage: exit-0 returns `True`, nonzero
  returns `False`, and an `OSError` from `subprocess.run` returns `False` without
  propagating — all three paths covered by new tests in test_goal.py.
- `landed_category_counts` has direct coverage proving that a two-token trailer
  (`idea-a landed`, no source) is skipped by the category counter while
  `landed_counts` still sees the idea — asserting the documented skip contract.
- The UI `do_GET` 404 branch has direct coverage: a request to an unknown path
  calls `send_error(404)` and does not call `send_response`, covered by
  `test_ui_handler_404_for_unknown_path` in test_ui.py.
- `_optional_int` in `config.py` rejects a TOML boolean (`true`/`false`) for
  `max_changed_files` with a `ConfigError` naming the file and field; the `bool`
  subclass-of-`int` loophole is closed by an explicit `isinstance(value, bool)` guard
  checked before the `isinstance(value, int)` check. Covered by a test in
  test_config.py.
- `_non_negative_int` and `_positive_float` in `cli.py` now have direct unit tests
  (`test_non_negative_int_and_positive_float_validators` in test_cli.py): both reject
  invalid values with `ArgumentTypeError` at parse time and accept valid ones.
- `Console.print`'s `sep` and `end` parameters now have direct coverage in
  test_console.py: multiple objects joined by a custom sep, and output with no
  trailing newline.
- `run_hook` now arms when `config.verify` is set (the natural opt-in), so
  the hook actually fires after `install-hook`; `config.hook` was always
  `False` (never loaded from TOML) making the hook permanently dormant.
  `cmd_install_hook` guidance updated. 13 tests cover the new arming contract,
  continuation behavior, and dormant-without-verify path.
- `test_run_hook_carries_count_across_continuations` proves the persisted count
  is read on continuation events: three invocations with `max_iterations=2`
  block the first two and allow on the third (cap reached).
- `test_batch_score_as_dict_pins_all_fields` pins all 6 fields of
  `BatchScore.as_dict()` (size, grounded, groundedness, flexibility, distinct,
  bounded), guarding the JSON output contract used by `propose --eval --json`.
- `test_goal_driver_recipe_includes_loop_hint_for_claude` and
  `test_goal_driver_recipe_omits_loop_hint_when_agent_unknown` monkeypatch
  `detect_agent` to verify the Claude-specific `/loop until: looptight goal check`
  line is included when agent is `"claude"` and absent otherwise.
- `test_install_goal_instructions_writes_managed_block_atomically` verifies that
  `install_goal_instructions` (which shares `_atomic_write` with its session sibling)
  leaves the original AGENTS.md intact and no `.tmp` behind when `os.replace` fails.

- `detect_verify` falls through when `package.json` has a non-dict top-level value
  (e.g. `[]`), exercising the `isinstance(manifest, dict)` guard — covered by
  `test_detect_verify_npm_non_dict_manifest_falls_through` in test_detect.py.
- A second call to `install_skill` overwrites stale content with the current `SKILL_MD`
  (idempotent-overwrite contract) — covered by
  `test_install_skill_overwrites_stale_content` in test_skill.py.
- `run --json` honors its contract on a config-guard failure: the no-headless,
  primary-worktree, no-agent, and no-verify guards emit a JSON error object (not Rich
  markup) when `--json` is set, covered by a test in test_cli.py.
- docs/unattended.md documents `--patience` and the escalation report, so value-aware
  stopping is discoverable (it stays off by default and a runtime-only control, not a
  config-file setting, by design); guarded by a doc test.
- The early-stop summary reads lean: the tail is a concise "stopped early" when an
  escalation block carries the why (no duplicate verdict), and a capped failure list
  shows "… and N more" (via `total_failures`) instead of truncating silently; covered
  by tests in test_summary.py.
- docs/usage.md documents `migrate`/the coordinator, which `doctor` prompts as setup
  but no setup guide explained; framed honestly (the loop also runs on file claims),
  guarded by a doc test in test_docs.py.
- `trajectory.clear()` now has direct coverage (`test_clear_drops_trajectory`): seeds
  a trajectory, clears it, and asserts the next `record` starts a fresh single-entry
  attempt; no production code change. `_is_fresh`'s non-numeric `updated_at` path
  (`trajectory.py:72`) is also covered by `test_record_treats_non_numeric_updated_at_as_stale`.
- `_verify_policy_error`'s `allowed_verify_commands` branch now has direct coverage:
  `test_verify_json_refuses_command_not_in_allowlist` in `tests/test_cli.py` configures
  an allowlist and verifies that a command outside it returns `status="error"` with
  `"not allowed by policy"` in the output.
- `_verify_policy_error`'s `max_changed_files` branch now has direct coverage:
  `test_verify_json_refuses_when_changed_file_count_exceeds_policy` in `tests/test_cli.py`
  configures `max_changed_files = 0`, creates one file, and asserts `status="error"` with
  `"max_changed_files"` in the output — all three policy branches are now directly tested.
- `summary.header()` `mode == "delegate"` branch is now covered:
  `test_summary_header_delegate_mode` in `tests/test_summary.py` builds a `RunResult`
  with `mode="delegate"` and asserts `"driving native loop"` in `summary.header(result)`.
- `render_rich()` diffstat branch is now covered: `test_console_summary_includes_diffstat`
  in `tests/test_summary.py` calls `render_rich` with a `RunResult(diffstat=...)` and
  asserts `"changes:"` and `"src/a.py"` appear in the captured output.
- `_parse_absolute_reset` noon (`12pm`) case is covered: `test_absolute_reset_handles_noon_12pm`
  in `tests/test_limits.py` calls `classify_limit` with `"resets at 12:00pm"` and a `now`
  30 min before noon, asserting 1800s wait — exercises the `hour != 12` guard that keeps
  noon at hour 12 without adding 12.
- `_git()` OSError fallback in `experience.py:28-29` is covered:
  `test_landed_counts_returns_empty_when_git_not_found` in `tests/test_experience.py`
  monkeypatches `subprocess.run` to raise `OSError` and asserts `landed_counts` returns
  `{}` — the documented contract when git is not on PATH.
- `_comments()` exception path in `discovery.py:138` is covered:
  `test_from_todos_skips_malformed_python_file` in `tests/test_propose.py` writes a file
  with a lone `\x00` byte, triggering `tokenize.TokenError`/`SyntaxError`, and asserts
  `from_todos()` returns `[]` without raising.
- `goal next` human output prefixes each build directive with "Iteration N:" so
  users can track progress across a multi-step loop; covered by
  `test_goal_next_human_output_includes_iteration_number` in tests/test_goal.py.
- The `stop` and `done` branches of `goal next` human output now have direct
  coverage: `test_goal_next_human_output_stop_and_done_branches` in tests/test_goal.py
  asserts "goal stop" on max-iterations and "goal done" on a passing done-check.
- `GoalDecision.as_dict()` now has direct unit coverage via
  `test_goal_decision_as_dict_pins_all_statuses` in tests/test_goal.py, asserting
  required fields are always present and optional fields appear only when set.
- The grounding gate tolerates line-range Evidence anchors: `_POSITION_SUFFIX` now
  strips `path:start-end` (and `path:start-end:col`) as a position, so a task citing a
  real file with an idiomatic line range resolves instead of being dropped as stale
  evidence. Filenames ending in `-N` with no colon are preserved; `path:line`/`:col`
  unchanged; swarm's stricter single-line planner check is untouched. Covered by
  `test_ref_resolves_handles_line_range_suffix`. (Boundary-bug theme: idiomatic anchors.)
- JS/TS TODO discovery ignores markers inside a multi-line backtick template
  literal: `_js_comments` now threads an `in_template` state across lines (as it
  already does `in_block` for `/* */`), and `_js_line_comment` accepts/returns that
  state, so a `// TODO` on a continuation line of a multi-line template string is no
  longer surfaced as a false-positive task. Single-line and block-comment behavior is
  unchanged. Covered by a from_todos multi-line-template test (mutation-verified) and
  updated `_js_line_comment` unit tests.
- `revert` checks for tracked changes before prompting: on a clean tree, plain
  `looptight revert` (no `--yes`) reports "nothing to revert" instead of offering to
  discard changes that do not exist; the dirty-tree `--yes` confirmation gate is
  unchanged. Covered by clean-no-prompt and dirty-still-prompts tests in test_cli.py.
- `doctor`/`status` honestly report the SQLite coordinator as the active claim
  store. `next` leases through the coordinator DB in any git repo, so doctor prints
  `coordinator: active` and a coordination line naming the SQLite coordinator, and
  `status` readiness/concurrency report the coordinator active. Concurrency is
  `unsafe` only outside Git or while live legacy file claims race the coordinator;
  a plain git repo with no legacy claims is `safe`. `migrate` is reframed as fencing
  live legacy file claims and is only hinted when such claims exist, never as a
  prerequisite for coordination (which already works). Covered by updated tests in
  test_cli.py and a plain-repo/legacy-claim concurrency pair. (User chose Fix B.)
- `goal` honors `--json` for every action: the set (`goal "<vision>" --json`) and
  clear (`goal clear --json`) actions now emit a versioned JSON object (set: `active`
  true plus the goal fields; clear: `active` false and a `cleared` boolean) instead of
  a bare human line, matching `goal status`/`goal next`. Human output is unchanged.
  Covered by set/clear JSON-contract tests in test_goal.py.
- The integration ref advance is proven to be a real compare-and-swap: when a racing
  integrator advances the target ref between our commit and our `update-ref`, the
  CAS (old-value `observed`) fails closed, the integration is marked `conflict` with
  no result published, and the racing commit is left intact rather than clobbered.
  Covered by `test_update_ref_cas_conflict_when_target_advances`; the test fails if
  the old-value argument is dropped from the update-ref call.
- Crash recovery uses the same compare-and-swap: if the target ref is advanced by
  another integrator while a crashed integration is being reconciled, `_reconcile_one`
  fails closed (`conflict`, "target advanced during reconcile") and leaves the racing
  commit intact instead of clobbering it. Covered by
  `test_reconcile_ref_advance_is_a_cas_against_a_racing_advance`; mutation-verified by
  dropping the old-value argument from the reconcile update-ref call.
- `atomic_write_text` now has direct unit coverage in `tests/test_fsutil.py`: happy
  path, nested parent-dir creation, and `OSError` cleanup (`.tmp` removed before
  re-raise). The module's docstring claim — "defined and tested in a single place" —
  now holds; no production code change.
- `from_lint`'s `except (OSError, subprocess.TimeoutExpired): return []` clause
  (discovery.py:481) now has direct regression coverage: two tests in `test_propose.py`
  inject `OSError` and `TimeoutExpired` into `subprocess.run` and assert `from_lint`
  returns `[]`; no production code change.
- `_js_line_comment` (discovery.py:142) now has direct unit coverage for four
  previously-untested branches: no-comment `(None, False)`, unclosed block
  `(body, True)`, closed inline block `(body, False)`, and backtick template-literal
  `(None, False)` — four new tests in `test_propose.py`; no production code change.
- JS/TS skipped-test discovery ignores skip markers inside a multi-line template
  literal or block comment: `from_skipped_tests`'s JS loop now threads `in_block`/
  `in_template` across lines (via the template-aware `_js_line_comment`) and skips
  lines that begin inside one, so an `it.skip(...)` written as example text in a
  multi-line backtick string is no longer a false-positive task. Single-line skip
  detection is unchanged. Sibling of the TODO template-literal fix; covered by a test.
- Python skipped-test discovery ignores skip markers inside a multi-line string:
  `from_skipped_tests` now suppresses candidate lines that fall inside a triple-quoted
  string (computed via `tokenize` in `_multiline_string_lines`), so a `pytest.skip(...)`
  written as example text in a docstring/multi-line string is no longer a false-positive
  task. The Python TODO path already had this via tokenize; the skip path now matches.
  Third sibling of the JS template-literal fixes; covered by a test.
- JS/TS TODO discovery is layout-agnostic like the Python path: `from_todos` now scans
  JS via a new `_all_js_files` that walks the whole tree (pruning vendored/build dirs),
  so a project using the common `app/`/`components/`/`lib/`/`pages/` layout with no
  top-level `src/` (React/Next/Vue) no longer has all its source TODOs silently missed.
  Vendored dirs stay pruned; skip discovery stays test-file-scoped. Covered by a test.
- JS skipped-test name extraction keeps nested quotes whole: `_JS_SKIP_NAME_RE` now
  captures to the matching closing quote of the same type as the opener (backreference),
  so `it.skip("name with 'apostrophe' inside")` yields the full name instead of
  truncating at the inner quote -- apostrophes in test descriptions are ubiquitous. An
  empty name still falls back to a generic label. Covered by a test.
- JS/TS TODO discovery finds markers in JSDoc-style block comments: `_js_comments`
  now strips the conventional leading ` * ` from block-comment continuation lines, so a
  ` * TODO: ...` inside a multi-line `/* ... */` or `/** ... */` block is matched instead
  of hidden behind the asterisk. Single-line `/* TODO */` and `// TODO` are unchanged.
  A real false-negative for idiomatic JS/TS; covered by a test.
- Skipped-test discovery covers stdlib `unittest`, not only pytest: `_is_skip_line`
  recognizes `@unittest.skip`, `@unittest.skipIf`/`skipUnless`, and `self.skipTest(...)`,
  and the conditional-guard check now also spares a guarded `self.skipTest`. The shared
  env-gate and `if`-guard classifiers decide rot vs intentional, so an env-gated
  `skipUnless(os.environ...)` is suppressed while an `@unittest.skip` or a real-condition
  skip is surfaced. A unittest-based project now gets skip discovery; pytest unchanged.
  Covered by a test.
- Discovery respects `.gitignore`: a `_not_ignored` helper filters the file walk
  through `git check-ignore` (batched, timeout-guarded), so TODOs/skips in gitignored
  generated/artifact dirs (`generated/`, `coverage/`, `.next/`, ...) no longer pollute
  the queue with non-fixable tasks. Tracked and untracked-but-unignored files (new
  work) are still scanned; outside Git or on any git error every path passes through,
  so discovery never depends on git succeeding. Covered by a test.
- `_statement_text` ignores parentheses inside string literals: it now counts `(`/`)`
  on `_code_only` (string-stripped) text, so an unbalanced paren in a skip
  `reason="..."` cannot over-extend the statement into later lines and make the
  env-gate classifier swallow an unrelated real-condition skip. The wrapped-skipif
  env-gate detection is otherwise unchanged. Covered by a test.
- `protected_paths` honors glob patterns: `_verify_policy_error` matches a changed
  file by exact path, directory prefix, OR `fnmatch` glob (`config/*`, `*.env`), so a
  `*` pattern actually protects its files instead of silently failing open on the
  safety gate. Exact and directory-prefix protection are unchanged. Covered by a test.
- `protected_paths` catches renames of protected files: `_changed_file_list` now splits
  a `git status` rename entry (`old -> new`) into both paths and strips git's quoting,
  so moving/renaming a protected file is refused instead of slipping past the gate (a
  plain delete was already caught; only the rename format evaded). Covered by a test.

- JS skip detection covers chained-modifier forms: `_JS_SKIP_RE` allows `skip`/`todo`
  anywhere in the `.`-chain after it/describe/test, so `test.concurrent.skip(...)`,
  `it.concurrent.skip(...)`, and `it.skip.each(...)` (Jest/Vitest) are surfaced. `skip`
  stays a whole chain token, so `it.skipFoo(`, `skipped`, and `it.only` are not false
  hits; plain and `x`-prefix forms are unchanged. Covered by a test.

- Imperative `pytest.xfail(...)` is detected like `pytest.skip(...)`: `_is_skip_line`
  now recognizes the runtime xfail call (its decorator form and the imperative skip
  were already caught), subject to the same conditional-guard check, so an
  unconditional `pytest.xfail` is surfaced as rot while a guarded one is spared.
  Covered by a test.

- Single-line parametrize-case skips are detected: `_is_skip_line` now recognizes
  `pytest.param(.., marks=pytest.mark.skip/skipif/xfail(..))` written inline (the
  standalone `marks=` line was already caught). It strips strings and a trailing
  comment first, so a `marks=...skip` mention in a comment or string is not a false
  hit, and the env-gate classifier still suppresses an `os.environ` skipif. Covered by a test.

- `TODO(author):` attributed markers are detected: `_TODO_RE` allows an optional
  `(author)` group after the marker word and drops it from the title, so the ubiquitous
  `# TODO(alice): ...` / `# FIXME(team): ...` convention (Google/Chromium/LLVM/Go) is
  surfaced in both Python and JS. Plain `# TODO:` is unchanged, and `# TODOS:` /
  `# fixme-style` prose stay rejected. Covered by a test.

- `TODO[ticket]:` and JSDoc `@todo` markers are detected: `_TODO_RE` allows a `[...]`
  attribution alongside `(...)` and an optional leading `@`, so issue-linked TODOs
  (`# TODO[#123]:`) and JSDoc `@todo` tags (` * @todo ...`) are surfaced with the
  attribution dropped from the title. `@param`, `@todoize`, and `# TODOS:` stay
  rejected; plain `# TODO:` is unchanged. Covered by a test.

- `detect_verify` detects a Makefile `check:` target (`make check`) as a fallback
  after `make test`, so a project using the GNU/autotools convention (or a `check:`
  run-all-checks target) is configured instead of falling back to the wrong default.
  `test:` is still preferred when both exist, and `checkfmt:`/`check-lint:` do not
  match. Covered by tests.

- Playwright's `test.fixme()` is detected: `fixme` joins `skip`/`todo` in the JS marker
  alternation, so `test.fixme(...)` and the chained `test.describe.fixme(...)` (a real
  skip in a top-tier framework) are surfaced. `fixme`-prefixed identifiers are not false
  hits; plain skip/todo/x-prefix detection is unchanged. Covered by a test.

- Jest `test.failing` and Vitest `test.fails` known-broken markers are detected: they
  join the JS marker alternation as the analogs of `pytest.xfail`/Playwright `test.fixme`
  (a test that runs and is expected to fail = known-broken to fix). `failsafe`/`failingly`
  identifiers are not false hits; plain skip/todo/fixme is unchanged. Covered by a test.

- Discovery covers TypeScript module extensions `.mts`/`.cts`: they join `_JS_EXTS`
  alongside the JS `.mjs`/`.cjs` pair (standard since TS 4.7), so TODO/skip markers in
  TypeScript ESM/CJS module files are no longer silently missed. Covered by a test.

- JS skip discovery scans Mocha's `test/` (singular) directory: `_js_discovery_files`
  adds `test` alongside `src`/`tests`, so a Mocha project's `it.skip` markers in
  plain-named `test/*.js` files (its default convention) are detected. The `tests/` and
  colocated `.test.`/`.spec.`/`__tests__/` patterns are unchanged. Covered by a test.

- Cypress `.cy.` test files are covered by colocated discovery: `_js_test_files` adds
  `.cy.` alongside `.test.`/`.spec.`, so a Cypress project's `it.skip` markers in
  `*.cy.ts`/`*.cy.tsx` files (in `cypress/` or colocated) are discovered. Existing
  patterns are unchanged. Covered by a test.

- `detect_verify` recognizes a `justfile`: a `justfile`/`Justfile`/`.justfile` with a
  `test:`/`check:` recipe detects `just test`/`just check` (the `make` recipe scan is
  now a shared `_recipe_runner` helper), so a `just`-only project is configured instead
  of falling back to the wrong default. Makefile detection is unchanged. Covered by tests.

- `detect_verify` recognizes a Deno project: `deno.json`/`deno.jsonc` markers map to
  `deno test`, alongside the cargo/go rules, so a Deno project is configured instead of
  defaulting wrong. Covered by tests.

- JS skip discovery scans Jasmine's `spec/` directory: `_js_discovery_files` adds
  `spec` alongside `src`/`tests`/`test`, so a Jasmine project's `it.skip` markers in
  plain-named `spec/*Spec.js` files are detected. Covered by a test.

- The task parser accepts `1)` paren-style ordered-list items: `from_task_file`
  matches `\d+[.)]` in both the item-detection and next-item-boundary regexes, so a
  `## Next`/task-file written with `1)` markers (valid markdown) is parsed instead of
  silently dropped into a false `no_work`. `1.` parsing and `-` bullet exclusion are
  unchanged. Covered by a test.

- `docs/usage.md` accurately describes the broadened discovery scope: the JS/TS family
  extensions (`.mjs`/`.cjs`/`.mts`/`.cts`), the `test/`/`spec/` directories, `*.cy.*`
  colocated files, `.gitignore` respect, and the full pytest/unittest + JS-framework
  marker set. A `test_docs.py` assertion locks `.mts`/`.cy.`/`.gitignore` so the doc
  cannot silently drift from the code again.

- The CHANGELOG `[Unreleased]` records the two `protected_paths` security fail-open
  fixes (glob patterns and renames) under a `### Security` subsection, so the safety-gate
  hardening is visible to anyone reviewing the next release.

- `docs/architecture.md` states the coordinator model consistently with the Fix-B
  reporting: the coordinator DB is the claim store in any git repository (so `doctor`/
  `status` report it active for a plain repo), and `migrate` fences the legacy file-claim
  mechanism rather than turning the coordinator on. The migrate facts are preserved.

- `docs/SPEC.md` no longer overclaims `--json`: the output contract names the nine
  machine-facing commands that take `--json` and notes that setup commands (`init`,
  `revert`) reject it, matching the README fix. A `test_docs.py` assertion locks it.

- The previously assertion-less proctree tolerance test now asserts its contract
  explicitly: `stop_process_tree` returns `None` on an already-reaped process (reached
  only if no exception was raised) and the process stays reaped — so a silent no-op
  regression would now fail it. It was the only assertion-less test in the suite.

- `write_config` writes `.looptight.toml` atomically via `atomic_write_text`, like the
  other user-file writers, so an interrupted `init` leaves no partial config behind
  (which `init` would otherwise refuse to overwrite, stranding the user). Covered by a
  failed-`os.replace` test that asserts no `.looptight.toml`/`.tmp` remains.

- `install-skill` tolerates a non-UTF-8 existing `SKILL.md`: the "already up to date"
  read now catches `(OSError, ValueError)` instead of only `OSError`, so an unreadable
  file is treated as not-current and rewritten rather than crashing with an uncaught
  `UnicodeDecodeError`. Matches the non-UTF-8 handling used by the other readers.

- Git network ops run non-interactively: `integration_queue._git` (push/fetch) and
  `swarm._git` (push) now run git with `GIT_TERMINAL_PROMPT=0` via a shared `_git_env()`,
  so a headless run can never hang on a credential prompt — a would-be hang becomes a
  fast failure the queue reports and retries. Credential helpers still work.

- `init` guides committing the new config: it writes an untracked `.looptight.toml`,
  and the documented next step `next` refuses a dirty worktree — so a first-run user
  who runs `init` then `next` hit a dead-end caused by init's own output. init now
  prints "Commit .looptight.toml before looptight next — it requires a clean worktree."

- Discovery bounds pathologically long marker text: a `TODO`/`FIXME`/skip on a
  minified, generated, or pasted long line no longer becomes a multi-hundred-KB task
  that floods host-agent context (one 200k-char line had produced a 196KB `propose`).
  `_todo_candidate` and the JS skip title truncate to 200 chars with an ellipsis via a
  shared `_bound`; the precise location still pinpoints the line.

- The grounding gate tolerates a backtick-delimited path with spaces: an anchor like
  `` `my src/a file.py:1` `` is delimited by its backticks, so the space is part of the
  path. Previously the bare-token rule cut it at the first space, so a real grounded
  status-next/task-file task whose file had a space was silently dropped as ungrounded.
  A fabricated space-path still fails `ref_resolves`, so precision is unchanged.

- `goal check --json` emits a machine verdict: the check action is an exit-code
  predicate (`/loop until: looptight goal check`), but it ignored `--json` entirely —
  printing human-colored text in its error branches and nothing in the predicate path,
  the lone goal action not honoring `--json`. It now prints a JSON verdict
  (`status`: done/pending/no_goal/no_done_check) while preserving the exit code.

- The goal done-check no longer pollutes `--json`: `run_done_check` ran the predicate
  without capturing its output, so a done-check that prints to stdout (test runners,
  grep, make — common) leaked into looptight's own stdout and corrupted `goal check
  --json` / `goal next --json`. The command is now run with `capture_output=True`
  (only its exit code matters), keeping looptight's stdout clean.

- The stop hook marks truncated verify output: `continuation_reason` fed the agent
  `verify.output[-3000:]` with no marker (even stripping a marker verify.py added
  upstream), so the agent mistook a partial tail for the whole — unlike the run loop's
  continuation context, which marks it. Both now share `VerifyResult.context_output`,
  fixing the hook and removing the drifted second copy of the truncation logic.

- `detect_verify` recognizes JVM projects: `build.gradle`/`build.gradle.kts` →
  `gradle test` and `pom.xml` → `mvn test`, preferring a committed wrapper
  (`./gradlew test` / `./mvnw test`) when present — the version-pinned, no-global-
  install way these tools standardly run. The dominant JVM ecosystem previously fell
  back to the wrong `pytest -q` default at init. Covered by tests in test_detect.py.

- `detect_verify` recognizes .NET: a `*.sln`/`*.csproj`/`*.fsproj`/`*.vbproj` file
  (matched by extension, since project files are arbitrarily named) maps to the
  unambiguous `dotnet test`, completing the dominant general-purpose ecosystems
  (JS/Python/Rust/Go/JVM/.NET). Covered by tests in test_detect.py.

- `detect_verify` recognizes Elixir (`mix.exs` → `mix test`) and Swift
  (`Package.swift` → `swift test`); both have a single unambiguous test runner.
  Ambiguous ecosystems (Ruby rake/rspec, PHP composer/phpunit) are deliberately left
  to the user, since a wrong auto-detected verify is worse than the pytest default.

- `settings._load`'s non-dict-JSON guard is covered: a settings.json holding valid
  JSON that is not an object (e.g. `[]`) is refused with a "JSON object" error and
  left untouched, so a regression cannot silently overwrite a foreign settings file.
  Test: `test_install_refuses_non_dict_json_settings_file` in test_settings.py.

- Two config-validation branches real misconfigs hit are now covered: a non-array
  `tasks` (`tasks = "TODO.md"` without brackets) and a quoted `max_changed_files`
  (`"5"`) each raise a `ConfigError` naming the field, so a regression loosening
  `_string_list`/`_optional_int` cannot let a malformed config through silently.
  Tests in test_config.py.
- `VerifyResult.context_output` has direct unit coverage: `test_context_output_passthrough_and_truncation_marker`
  in tests/test_verify.py asserts the short path returns the text unchanged (no truncation
  marker), the long path prefixes the tail with `[...N earlier characters truncated...]`, and
  output exactly at the limit passes through without an off-by-one marker.
- `_not_ignored`'s `TimeoutExpired` branch has direct regression coverage:
  `test_not_ignored_falls_through_on_timeout` in tests/test_propose.py monkeypatches
  `discovery.subprocess.run` to raise `TimeoutExpired` and asserts `_not_ignored` returns all
  input paths unchanged — sibling of the existing OSError test (test_propose.py:588).
- `_has_dirty_git_worktree`'s `OSError` branch has direct unit coverage:
  `test_has_dirty_git_worktree_returns_false_on_oserror` in tests/test_tasks.py monkeypatches
  `tasks.subprocess.run` to raise `OSError` and asserts the function returns `False` instead of
  propagating the exception — sibling of `test_checkpointer_is_a_noop_when_git_cannot_launch`.
- `Checkpointer.restore()` enabled+no-snapshots path is covered:
  `test_restore_returns_false_when_enabled_but_no_snapshots` in tests/test_checkpoint.py creates
  a Checkpointer in a real git repo (enabled=True), leaves snapshots empty, and asserts
  `restore()` returns `False` without raising — the `if not target: return False` branch at
  checkpoint.py:95.

- `_parse_relative_reset`'s unrecognized-unit fallback (`1.0`) in `limits.py:86` is covered:
  `test_classify_limit_uses_default_1_second_for_unrecognized_unit` in tests/test_limits.py
  calls `classify_limit("rate limit; retry after 5 fortnights")` and asserts
  `signal.retry_after_s == 5.0` — the `.get(..., 1.0)` default branch.

- `rank()`'s unknown-source score-0 fallback (`ranking.py:43`) is covered:
  `test_rank_unknown_source_scores_zero` in `tests/test_propose.py` creates a `Candidate`
  with `source="unknown-source"` and asserts `rank([c])[0].score == 0.0` — the
  `.get(c.source, 0)` default branch that all prior tests bypassed.

- `_outcome()` in `daemon.py:71-72` returns `("fault", merged>0)` when a run errors after
  some workers merged: `test_outcome_fault_with_merged_workers` in `tests/test_daemon.py`
  calls `_outcome` directly with `SwarmResult(reason=REASON_ERROR, merged=1)` and asserts
  `outcome == "fault"` and `merged == 1` — the fault-with-progress branch previously
  untested (all prior error tests used the default `merged=0`).
- `rank_with_model()`'s unknown-source score-0 branch (`ranking.py:55`) is covered:
  `test_rank_with_model_unknown_source_scores_zero` creates a `Candidate` with
  `source="mystery"` and asserts `rank_with_model([c], Model())[0].score == 0.0` — the
  `.get(c.source, 0)` default combined with `reweight_factor` path.
- `reweight_factor()`'s equal-split midpoint (`experience.py:105`) is covered:
  `test_reweight_factor_equal_split_returns_midpoint` calls `reweight_factor("lint",
  Model(category_landed={"lint": 1}, category_failed={"lint": 1}), lo=0.5, hi=1.5)` and
  asserts the result equals `1.0` — the `rate=0.5` path previously exercised only at
  extremes.
- `_recipe_runner()`'s `except (OSError, ValueError): return None` branch (`detect.py:125`)
  is covered for justfile: `test_detect_verify_non_utf8_justfile_falls_through` writes a
  `justfile` with non-UTF-8 bytes and asserts `detect_verify` returns `None` — the sibling
  of the existing Makefile test, exercising the same exception path via the justfile branch.
- `_summarize("no_progress", total>0, persisted=True)` is now covered:
  `test_summarize_no_progress_persisted_failures` calls `_summarize("no_progress", total=2,
  persisted=True, iterations=3)` and asserts both "Improved, then stalled" and "never
  cleared" appear — the fourth branch previously untested (`metacog.py:167-168`).
- `_normalize_failure`'s `_HEX_ADDR_RE` and `_IN_SECONDS_RE` branches are now covered:
  `test_normalize_failure_replaces_hex_addresses` asserts `"0xADDR"` replaces `0xDEADBEEF`,
  and `test_normalize_failure_normalizes_in_seconds_fragment` asserts "in 2ms" becomes "in Ns"
  — the two regex paths previously untested directly (`metacog.py:112-113`).

- `_is_ancestor()`'s empty-string early-return guards are now covered:
  `test_is_ancestor_returns_false_on_empty_sha` calls `_is_ancestor(tmp_path, "", "abc")` and
  `_is_ancestor(tmp_path, "abc", "")`, asserts both return `False`, and asserts git was never
  invoked — covering the two `if not sha or not tip: return False` branches at
  `integration_queue.py:357-358`.

- `experience.py`'s `_git()` now passes `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}` to
  `subprocess.run`, matching the same non-interactive guard used by `integration_queue` and
  `swarm`, so a `git log` call from the experience module cannot hang on a credential prompt in
  headless mode. Covered by `test_experience_git_sets_terminal_prompt_env` in test_experience.py.
- `checkpoint._git()` passes `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}` via a local
  `_git_env()`, matching the same non-interactive guard in `integration_queue`, `swarm`, and
  `experience`; `import os` added. A new test monkeypatches `subprocess.run` directly and
  asserts the env dict contains `GIT_TERMINAL_PROMPT` equal to `"0"`. Covered by
  `test_checkpoint_git_sets_git_terminal_prompt_env` in test_checkpoint.py.
- `read_goal`'s `not isinstance(data, dict)` branch (`goal.py:60`) is now covered:
  `test_read_goal_returns_none_when_json_is_not_a_dict` in test_goal.py writes `[]` to
  `goal_path(repo)` and asserts `read_goal(repo)` returns `None` without raising — the path
  where valid JSON that is not a dict is silently discarded rather than crashing.
- `_has_dirty_git_worktree`'s non-zero-returncode path (`tasks.py:90`) is now covered:
  `test_has_dirty_git_worktree_returns_false_on_nonzero_returncode` in test_tasks.py
  monkeypatches `subprocess.run` to return `CompletedProcess` with `returncode=128` and
  asserts `_has_dirty_git_worktree` returns `False` via the `returncode == 0` short-circuit.
- `cmd_statusline`'s `project_dir` fallback is covered:
  `test_statusline_uses_project_dir_when_current_dir_absent` in test_cli.py passes
  `{"workspace": {"project_dir": str(tmp_path)}}` on stdin (no `current_dir`) and asserts
  `statusline` reads swarm state from `tmp_path` correctly — a regression removing the
  branch would now be caught.
- `claim_dir`'s `OSError` branch (`claims.py:54`) is covered:
  `test_claim_dir_returns_none_on_oserror` in test_claims.py monkeypatches
  `claims.subprocess.run` to raise `OSError` and asserts `claim_dir` returns `None`
  without propagating the exception.
- `_not_ignored`'s `ValueError` branch (`discovery.py:98`) is covered:
  `test_not_ignored_falls_through_when_path_outside_root` in test_propose.py passes a
  path outside `root`, triggering `relative_to` to raise `ValueError`, and asserts
  all input paths are returned unchanged.
- `_not_ignored` in `discovery.py` now passes `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}`
  to its `git check-ignore` subprocess, matching every other git call in the codebase
  (`checkpoint.py`, `integration_queue.py`, `experience.py`, `swarm.py`) so a headless run
  cannot block on a credential prompt. Covered by
  `test_not_ignored_git_sets_terminal_prompt_env` in test_propose.py.
- `_has_dirty_git_worktree` in `tasks.py` now passes `env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}`
  to its `git status --porcelain` subprocess; `import os` added. A headless `looptight next`
  can no longer block waiting for git credentials via this path. Covered by
  `test_has_dirty_git_worktree_sets_terminal_prompt_env` in test_tasks.py.
- `_rel`'s `ValueError` branch (`discovery.py:176`) is covered:
  `test_rel_returns_absolute_string_when_path_outside_root` in test_propose.py calls
  `_rel(Path("/a"), Path("/b/c.py"))` and asserts the result is `"/b/c.py"`.
- `verify.py`'s `except OSError` branch (`verify.py:90`) is covered by a true
  `OSError` injection: `test_popen_oserror_is_launch_error` in test_verify.py
  monkeypatches `subprocess.Popen` to raise `OSError` and asserts `error="launch_error"`
  with `exit_code==127` — distinct from the shell-127 path.

- `stop_process_tree`'s POSIX OSError fallback to `process.kill()` is covered:
  `test_stop_process_tree_falls_back_to_kill_when_killpg_raises_oserror` in
  tests/test_proctree.py monkeypatches `os.killpg` to raise a generic `OSError`
  (not `ProcessLookupError`) and asserts the final `process.kill()` runs and the
  call returns `None`, so a killpg EPERM-style failure cannot orphan the child.

- `_verifier_quality` classifies by the strongest signal, not the first match:
  the `lint-only` check now runs last (after e2e/integration/unit), so a command
  that runs tests *and* a linter (`uv run pytest -q && uv run ruff check`, this
  repo's own verify) reports `unit` instead of short-circuiting to `lint-only`.
  Found by dogfooding `looptight status`. A pure-lint command still classifies
  as `lint-only`. Covered by
  `test_status_json_classifies_tests_plus_lint_as_unit_not_lint_only` in test_cli.py.

- SPEC's Output contract no longer overclaims `propose --json`: it names the
  deliberate exception — a bare ranked candidate list with no schema-version
  envelope, preserved byte-for-byte (and `--eval` wrapping it as
  `{candidates, eval}`) — matching `protocol_commands.py:181`. Locked by
  `test_spec_output_contract_documents_propose_json_bare_list` in test_docs.py.

- `_verifier_quality` classifies the unambiguous single-runner test commands
  detect_verify auto-selects (cargo/go/deno/mix/swift/dotnet/gradle/gradlew/mvn/
  mvnw test) as `unit`, so `status`/`doctor`/`init` no longer call a Rust/Go/.NET/
  JVM/Elixir/Swift user's own detected test command "custom/unknown". make/just
  recipes stay `custom/unknown` (arbitrary). Found by the bug-hunt audit; covered
  by `test_status_json_classifies_detected_runners_as_unit` in test_cli.py.

- `_verifier_quality` ignores a negated-marker deselection: a pytest
  `-m "not integration"` / `not e2e` clause is stripped before the substring scan
  (`scan = normalized.replace("not integration","")...`), so a command that
  *excludes* those markers classifies by its real runner (`unit`) instead of being
  mislabeled `integration`/`e2e`. Real path/marker integration and `playwright`
  e2e commands are unchanged. Found by the audit; covered by
  `test_status_json_ignores_negated_marker_deselection` in test_cli.py.

- `max_changed_files` counts a rename as one file, not two: a new `_changed_entries`
  helper yields one entry per `git status` line (a rename carries both sides), the
  count gate uses `len(entries)`, and `_changed_file_list` flattens entries for the
  protected-path scan and human display (both-sides contract unchanged). So renaming
  one tracked file under `max_changed_files = 1` passes the count gate instead of
  being wrongly blocked. Found by the audit; covered by
  `test_max_changed_files_counts_a_rename_as_one_file` in test_cli.py.

- The daemon no longer backs off mid-progress: `_outcome` treats a round that
  merged work but had a worker fail its grounded task (`reason=REASON_ERROR` with
  NO top-level error — the normal case) as `progress` (loop on immediately, delay 0),
  per the daemon's own contract. A genuine fault (a top-level error message — failed
  push, broken verify) still backs off even with merged work. Found by the audit;
  covered by `test_daemon_treats_a_merged_round_as_progress_despite_reason_error`
  and `test_daemon_backs_off_on_a_genuine_error_even_with_merged_work` in test_daemon.py
  (and the corrected `test_outcome_genuine_fault_with_merged_workers`).

- The continuous-swarm start banner renders an unbounded run honestly: `_swarm_banner`
  prints "continuous · unbounded rounds" for `max_rounds == 0` (the default, meaning
  run until no work/failure/interruption) instead of the misleading "max 0 rounds"
  cap. Found by the audit; covered by `test_swarm_banner_renders_unbounded_for_zero_max_rounds`
  and the updated `test_swarm_banner_notes_resume_on_limit` in test_swarm.py.

- `--model` reaches the native (`--native`) delegate loop, not only the supply path:
  `drive_native_loop` now takes a `model` param (base + claude adapter), loop.py passes
  `config.model`, and `ClaudeAdapter._invoke` appends `--model`. Previously the native
  path hardcoded `None`, silently discarding a user's `--model opus` in native mode.
  Found by the audit; covered by `test_claude_native_loop_threads_the_configured_model`
  in test_adapters.py (stubs updated to accept the param).

- `score_status_next().bounded` now actually guards the upper bound: `from_task_file`/
  `from_status_next` take a `cap` (default 6, preserving the `next`/`propose` cap), and
  the eval reads the *uncapped* Next section, so a `## Next` with 8+ tasks scores
  `size=8, bounded=False` instead of the old truncated `size=6, bounded=True`. The
  `size <= 6` half of the eval's 1-6 guard was previously dead code and the misleading
  value reached `propose --eval-batch --json`. Found by the audit; covered by
  `test_score_status_next_flags_an_over_budget_section_as_unbounded` in test_idea_eval.py.

- `summary_text`'s positive planner note names actionable task sources, not opaque
  ids: the "paid off" line now reads from `model.category_landed` ("Task sources that
  have paid off (favor them): status-next, todo") instead of 12-hex `model.landed`
  idea hashes the planner cannot map. Matches the negative `category_failure_reasons`
  line, which already names sources. Empty-guard updated accordingly. Found by the
  audit; covered by `test_summary_text_names_paid_off_sources_not_opaque_ids` in
  test_experience.py.

- The trailing-position-suffix stripper is unified: `grounding.py` exports one
  range-aware `strip_position_suffix` (used by `ref_resolves`), and `idea_identity._path`
  imports it instead of its own non-range-aware `(:\d+)+$` regex. The two had drifted
  (grounding tolerated `:start-end`, idea_identity did not), so a future `path:start-end`
  location would have minted a fresh `idea_id` per line shift, breaking the cooldown/
  self-model keying. Found by the audit; covered by
  `test_identity_is_stable_across_a_line_range_location` in test_idea_identity.py.

- `docs/usage.md` describes the claim model accurately: it no longer says the solo
  loop runs on "file-based claims" until `migrate`. The §"Activate the coordinator"
  section now states `next` claims through the repo-private SQLite coordinator in any
  Git repo from the first run, and that `migrate` *fences the legacy file-claim
  mechanism* rather than switching the store on — matching tasks.py and architecture.md.
  Found by the docs audit; locked by `test_usage_doc_describes_the_coordinator_claim_model_accurately`
  in test_docs.py. Consistent with the Fix-B coordinator reporting decision.

- The README Commands list documents `looptight revert` (undo the agent's uncommitted
  edits, restoring to HEAD), so a stuck user can find their undo alongside its peers;
  it was previously only named in a SPEC parenthetical. Found by the docs audit; locked
  by `test_readme_documents_the_revert_recovery_command` in test_docs.py.

- `claim()`'s stale-task sweep no longer completes a *different* worktree's live lease.
  The `runs` table records each run's per-worktree `owner` (schema v4, guarded 3→4
  migration; `start_run`/`claim` take `owner`; tasks.py passes `owner_id(workdir)`), and
  the sweep spares a live-leased out-of-set task only when both its lease-run owner and
  the caller's owner are known and differ. Same-worktree reconcile (same owner) and
  owner-less runs still retire, so the documented single-writer reconcile is unchanged.
  Resolves the divergent-worktree race the concurrency audit found. Covered by
  `test_claim_spares_a_different_owners_live_lease` and
  `test_claim_still_completes_a_same_owner_out_of_set_task` in test_coordinator.py;
  backward compatible (existing owner-less coordinator tests unchanged).

- The CHANGELOG `[Unreleased]` no longer carries the stale "solo loop runs on file
  claims" model: the readiness-change entry now states the coordinator is the claim
  store in any Git repo whether or not `migrate` has run (which fences legacy file
  claims), matching tasks.py and the corrected usage.md/architecture.md. Locked by
  `test_changelog_unreleased_does_not_claim_solo_loop_runs_on_file_claims` in test_docs.py.

- The early-stop NO_PROGRESS summary is honest about a regress: it reads "Improved
  earlier, then made no further progress across N tries" instead of "Improved, then
  stalled", which misreported an improve-then-regress trajectory (the branch fires for
  both stall and regress). Upholds the SPEC honest-signals principle. Covered by the
  updated `test_summarize_no_progress_persisted_failures` in test_metacog.py; the
  `escalated` line and StopReason/advice are unchanged.

- The coordinator v3→v4 migration upgrade path is covered:
  `test_migration_v3_to_v4_adds_owner_column` in test_coordinator.py builds a v3 DB
  (runs table without `owner`, `user_version = 3`), opens it, and asserts the migration
  added `runs.owner`, bumped `user_version` to 4, and an owner-scoped `claim` works —
  matching the existing v1→v2 and v2→v3 migration tests, so the new owner migration
  cannot silently break a real user's existing DB on a future edit.

- The "unsupported coordinator schema" version-skew guard is covered:
  `test_open_rejects_a_newer_unsupported_schema_version` in test_coordinator.py writes a
  DB with `user_version = 99` and asserts `Coordinator.open` raises `RuntimeError`
  containing "unsupported coordinator schema", so opening a DB written by a newer
  looptight (after a downgrade) fails clearly instead of misbehaving. No production change.

- Two skip-discovery boundary guards on bad files are covered:
  `test_skip_discovery_tolerates_bad_files` in test_propose.py asserts
  `_multiline_string_lines` returns `set()` on a malformed Python file (lone `\x00`) and
  `_js_comments` yields nothing on an unreadable path (a directory), both without raising
  — so discovery degrades quietly rather than crashing the loop on bad repo content.
  No production change.

- `goal next`'s human no-goal message is covered:
  `test_goal_next_human_output_reports_no_goal` in test_goal.py runs `goal next` in a repo
  with no goal set and asserts exit 0 with "no active goal" in the output, so a user who
  runs `goal next` before setting a goal is still guided to set one. No production change.

- `coordinator_path`'s git-not-installed (OSError) fallback is covered:
  `test_coordinator_path_is_none_when_git_is_not_installed` in test_coordinator.py
  monkeypatches `subprocess.run` to raise `OSError` and asserts `coordinator_path` returns
  `None`, so the coordinator is gracefully unavailable (the loop falls back to file claims)
  when git is not on PATH — distinct from the covered not-a-repo path. No production change.

- Two coordinator "unknown id → safe no-op" guards are covered:
  `test_coordinator_unknown_id_lookups_are_safe_no_ops` in test_coordinator.py asserts
  `lease_for` returns `None` for an unmatched fingerprint/run and `finish_integration`
  returns without raising or changing state on an unknown integration id — so a stale or
  mistaken id cannot crash the coordinator. No production change.

- `_readiness_remediation`'s missing-agent branch is covered:
  `test_readiness_remediation_for_missing_agent` in test_cli.py asserts that with
  verify/git/task_sources healthy but `agent == "missing"`, the guidance is "install a
  supported agent CLI" — the lone remediation branch the status integration tests do not
  reach. No production change.

- Module-level `pytestmark = pytest.mark.skip` skip detection is covered:
  `test_module_level_pytestmark_skip_is_surfaced` in test_propose.py asserts the
  whole-module skip assignment form is surfaced as one candidate, while an env-gated
  `skipif` assignment stays suppressed as intentional infrastructure. No production change.

- `from_lint`'s skip-unparseable-output-line guard is covered:
  `test_from_lint_skips_unparseable_output_lines` in test_propose.py injects a stray
  non-matching ruff line alongside one real `path:line:col: CODE msg` and asserts only the
  real finding is surfaced, so an unexpected ruff format line cannot be mis-surfaced as a
  lint task. No production change.

- JS skip detection inside a multi-line block comment is covered:
  `test_js_skip_inside_multiline_block_comment_is_ignored` in test_propose.py asserts an
  `it.skip(...)` on a continuation line of a `/* */` block comment is ignored (commented-out
  example), while a real `it.skip` outside the comment is still surfaced — exercising the
  scanner's cross-line `in_block` tracking. No production change.

- Two discovery parser boundary branches are covered:
  `test_conditional_skip_with_blank_line_in_block_is_suppressed` asserts a `pytest.skip()`
  under an `if` with a blank line between stays classified conditional (suppressed), and
  `test_adjacent_numbered_items_without_blank_line_parse_separately` asserts two adjacent
  `## Next` items with no blank line parse as two tasks — both in test_propose.py. No
  production change.

- The continuous-swarm planner grounding gate's three remaining branches are covered:
  `test_planned_tasks_grounded_rejection_branches` in test_swarm.py asserts
  `_planned_tasks_are_grounded` rejects a candidate with no evidence anchor, accepts
  path-only evidence to a real file, and rejects an evidence line past the file end — so
  the gate that stops the continuous swarm acting on fabricated or out-of-range planned
  tasks is fully exercised. No production change.

- The swarm's "never merge unverified work" guarantee is covered:
  `test_swarm_does_not_merge_work_that_fails_verify` in test_swarm.py runs `run_swarm` with
  `verify="exit 1"` and the editing fake adapter, asserting the result is not passed, every
  worker is `failed`, the base repo's files are unchanged (no merge), and the failed
  worktrees are retained — the core safety path no prior scenario exercised (all used
  `verify="exit 0"`). No production change.

- The swarm "agent produced no changes" rejection is covered:
  `test_swarm_rejects_a_worker_that_produces_no_changes` in test_swarm.py uses a no-op
  adapter (success but no edits) and asserts the worker is `failed` with "agent produced no
  changes" rather than merged as an empty result — the no-op branch no prior adapter
  exercised. No production change.

- The swarm serialized-integration merge-conflict path is covered end-to-end:
  `test_swarm_marks_a_conflicting_worker_as_conflict` in test_swarm.py runs two workers that
  rewrite the same file with conflicting content and asserts one `merged`, one `conflict`
  (worktree retained), with the base tree left coherent — so the conflict-abort path in
  `_integrate` is exercised, not just the integration-queue unit tests. No production change.

- `cmd_swarm`'s human error and NO_WORK output branches are covered:
  `test_swarm_cli_prints_error_and_no_work_results` in test_swarm.py monkeypatches
  `run_swarm` to return a canned errored result (asserts "swarm error: boom" printed) and an
  empty no-work result (asserts "NO_WORK" printed, exit 0), via the `swarm --headless` CLI.
  No production change.

- The codex/opencode adapter non-zero-exit failure paths are covered:
  `test_codex_and_opencode_surface_nonzero_exit_as_failure` in test_adapters.py drives both
  adapters directly (independent of provider availability, which the parametrized test
  filters on) with a non-zero `run_command`, asserting `run_iteration` returns `ok=False`
  with an error and the return code — so a regression in either provider's error handling is
  caught even when they are not on PATH. No production change.

- `stop_active_processes` interrupt cleanup is covered:
  `test_stop_active_processes_terminates_registered_processes` in test_adapters.py registers
  a real long-running process in `_ACTIVE_PROCESSES`, calls `stop_active_processes`, and
  asserts it is terminated (cleaning up the registry) — so an aborted swarm tearing down its
  provider processes is exercised. No production change.

- The integration queue's git-failure robustness is covered:
  `test_integration_queue_handles_git_failures` in test_integration_queue.py asserts
  `git_common_dir` raises `IntegrationError` outside a repo and `_git` returns returncode 127
  when `subprocess.run` raises `OSError` — so a git failure cannot crash the durable
  integrator. No production change.

- `prepare_integration_worktree` rejecting an unresolvable target ref is covered:
  `test_prepare_integration_worktree_rejects_an_unresolvable_ref` in test_integration_queue.py
  asserts it raises `IntegrationError` for a nonexistent ref in a real repo — the guard that
  stops the integrator preparing a worktree for a ref that does not exist. No production change.

- The crash-recovery trailer lookups' git-failure fallbacks are covered:
  `test_trailer_lookups_return_none_on_git_failure` in test_integration_queue.py monkeypatches
  `_git` to fail and asserts both `_trailer_commit_on_ref` and `_committed_result_in_worktree`
  return `None`, so idempotent crash recovery does not blow up on a transient git error. No
  production change.

- `cmd_verify`'s config-error and policy-error output branches are covered:
  `test_verify_reports_config_and_policy_errors` in test_cli.py asserts `verify` (human and
  `--json`) reports a config error on a malformed `.looptight.toml` (exit 2) and a "policy
  error:" on a protected-path change (exit 2) — the verify config-error path and the
  policy-error human path that the JSON-only policy tests did not reach. No production change.

- `plan_next_tasks`'s git-precondition failure is covered:
  `test_plan_next_tasks_fails_gracefully_outside_a_git_repo` in test_swarm.py asserts it
  returns `PlanningResult("failed", ...)` with a Git-repository message outside a repo — so
  the daemon's continuous planner keeps its footing rather than crashing. No production change.

- `plan_next_tasks`'s planner-provider-failure branch is covered:
  `test_plan_next_tasks_fails_when_planner_provider_fails` in test_swarm.py uses a planner
  adapter that writes docs/STATUS.md but returns `ok=False`, and asserts `plan_next_tasks`
  returns `status="failed"` with the provider error — so a crashed planning provider is a clean
  failure, not an accepted plan. No production change.

- `plan_next_tasks`'s off-scope-change rejection is covered:
  `test_plan_next_tasks_rejects_changes_outside_status_md` in test_swarm.py uses a planner
  adapter that edits a non-STATUS file and asserts `plan_next_tasks` returns `status="failed"`
  — so the planner may only refresh docs/STATUS.md. No production change.

- `plan_next_tasks`'s planner-no_work path is covered:
  `test_plan_next_tasks_returns_no_work_when_planner_makes_no_changes` in test_swarm.py uses a
  planner adapter that edits nothing (`ok=True`) and asserts `plan_next_tasks` returns
  `status="no_work"` (the continuous swarm's stop signal). No production change.

- The swarm worker rate-limited status is covered:
  `test_swarm_marks_a_rate_limited_worker_as_limited` in test_swarm.py uses an adapter
  returning a rate-limit error and asserts the worker is `limited` (not `failed`), so the
  continuous swarm can wait it out. No production change.

- `render_rich`'s escalation evidence path (summary.py:91-93) now has direct coverage:
  `test_render_rich_shows_escalation_evidence_in_rich_output` in tests/test_summary.py
  builds a `RunResult` with a populated `Escalation`, calls `render_rich`, and asserts
  the summary text and failure line appear in the captured output — the `if evidence:`
  branch was previously dead in the suite. No production change.

- Five `ClaimStore` boundary guards in claims.py are covered (tests in test_claims.py):
  `has_live_claim` returns False when the only claim is expired, `select()` returns None when
  all tasks are claimed by another owner, `summary()` returns `(None, 0)` with an absent root
  dir, `_claim()` rejects a falsy task id, and `_read()` degrades a corrupt JSON file to `{}`.
  No production change.

- `trajectory._read()`'s wrong-schema_version guard is covered:
  `test_trajectory_read_returns_none_for_wrong_schema_version` in test_trajectory.py writes a
  well-formed JSON file with `schema_version: 99` and asserts `_read` returns None, so a
  forward-incompatible trajectory file cannot poison value-aware stopping. No production change.

- `settings.py` path helpers and absent-file `uninstall` are covered:
  `test_settings_path_helpers_and_absent_file_uninstall` in test_settings.py asserts
  `user_settings_path()`/`project_settings_path(root)` return the expected `.claude/settings.json`
  layout and `uninstall` on a non-existent path returns 0 without raising. No production change.

- The swarm worker change-detection-failure path is covered:
  `test_swarm_fails_worker_when_change_detection_fails` in test_swarm.py monkeypatches
  `_worker_changed_paths` to return `(None, error)` and asserts the worker is `failed` with that
  error, so an undeterminable change set is not integrated. No production change.

- Two `cmd_daemon` CLI guards are covered:
  `test_daemon_cli_rejects_too_many_workers_and_missing_verify` in test_cli.py asserts
  `daemon --workers 51` exits 2 with a "workers must be" message and `daemon` with no detectable
  verify exits 2 with a verify message. No production change.

- `cmd_run`'s NotImplementedError handler is covered:
  `test_run_reports_not_implemented_from_loop_with_exit_3` in test_cli.py stubs `run_loop` to
  raise `NotImplementedError` (with `direct_main=true`) and asserts `run --headless` exits 3
  carrying the message rather than crashing. No production change.

- `stop_process_tree`'s final-kill OSError swallow is covered:
  `test_stop_process_tree_swallows_a_final_kill_oserror` in test_proctree.py makes `os.killpg`
  raise and a fake process whose `kill()` also raises `OSError`, asserting `stop_process_tree`
  returns `None` without raising — best-effort teardown never raises. No production change.

- `proctree.py`'s remaining uncovered branches are now covered:
  `test_new_process_group_kwargs_fallback_for_unknown_os` covers the `return {}` fallback and
  `test_stop_process_tree_taskkill_oserror_falls_through_to_kill` covers the Windows taskkill
  `OSError` path; proctree.py reaches 97% (one Windows-only line remains untestable on Linux).
  `run_hook`'s valid-JSON-non-dict guard (`hook.py:120`) is covered by
  `test_run_hook_tolerates_valid_json_non_dict_event`; `hook.py` is now 100%. No production change.


- `cmd_run`'s no-agent and no-verify guard-fails are covered:
  `test_run_guard_fails_without_agent_or_verify` in test_cli.py asserts `run --headless`
  (with `direct_main=true`) exits 2 with a "no coding agent" message when `detect_agent` returns
  None and with a "verify" message when no verify is configured or detectable. No production change.

- `cmd_daemon`'s per-cycle output, fault hook, and stop summary are covered:
  `test_daemon_cli_renders_cycle_outcomes_and_stop_summary` in test_cli.py stubs `run_daemon`
  to invoke `on_cycle` (progress + fault) and `on_fault` (with `--on-fault true`), asserting the
  per-cycle lines, the fault detail, and the "daemon stopped" summary are printed. No production change.

- The `install-hook` command's install/already-installed/uninstall paths are covered:
  `test_install_hook_command_install_already_and_uninstall` in test_cli.py drives
  `install-hook --project` (isolated to cwd/.claude, never the user's real settings) and asserts
  "installed", then "already installed", then `--uninstall` "removed", each exit 0. No production change.

- `cmd_statusline`'s never-break-the-editor fallback is covered:
  `test_statusline_command_falls_back_to_idle_on_error` in test_cli.py feeds `{}` on stdin,
  monkeypatches `read_state` to raise, and asserts `statusline` exits 0 printing "looptight: idle".
  No production change.

- The `hook` command wrapper is covered:
  `test_hook_command_runs_run_hook_and_returns_a_code` in test_cli.py feeds a Stop-hook JSON event
  on stdin (in a repo with no verify, so the hook is dormant) and asserts `main(["hook"])` returns
  0 without raising. No production change.

- The `install-skill` command's install/already-up-to-date paths are covered:
  `test_install_skill_command_install_and_already_current` in test_cli.py sets `$HOME` to a tmp
  dir (isolating the write from the user's real `~/.claude`) and asserts `install-skill` prints
  "installed" then "already up to date", each exit 0. No production change.

- `_doctor_next_setup_command` branches and `cmd_revert`'s not-a-repo guard are covered:
  `test_doctor_next_setup_command_branches` asserts each readiness→command mapping (no verify→init,
  no git→repo, no agent→install, all ready→next) and `test_revert_in_non_git_dir_reports_nothing`
  asserts `revert` outside a git repo exits 1 with a "not a git repo" message — both in test_cli.py.
  No production change.

- `cmd_next`'s generic-error human output is covered:
  `test_next_human_output_prints_a_generic_error` in test_cli.py monkeypatches `next_task` to
  return an error `NextResult` and asserts `next` prints "error:" with the message (the non-dirty
  else branch). No production change.

- `render_state_panel`'s goal-truncation and worker-error display are covered:
  `test_render_state_panel_truncates_goal_and_shows_error` in test_ui.py renders a state with a
  long-goal worker and an errored worker, asserting the panel truncates the goal ("...") and shows
  the error in brackets. No production change.

- `ui.read_state`'s wrong-schema-version fallback is covered:
  `test_read_state_returns_empty_on_wrong_schema_version` in test_ui.py writes a state file with
  `schema_version: 99` and asserts `read_state` returns `empty_state()`, so a forward-incompatible
  state file cannot break the read-only view. No production change.

- `ui._state_path`'s in-repo (Git common dir) branch is covered:
  `test_state_path_in_git_repo_uses_common_dir` in test_ui.py asserts that inside a `git init`-ed
  dir the state path is under the Git common dir and named `STATE_FILE` (not the outside-Git
  `.looptight` fallback). No production change.

- `plan_next_tasks`'s plan-verify-failure branch is covered:
  `test_plan_next_tasks_fails_when_plan_verify_fails` in test_swarm.py uses `PlanningAdapter` with
  `verify="exit 1"` and asserts the planner rejects the plan with `status="failed"` mentioning
  planner verify, so a plan that breaks the build is not accepted. No production change.

- `plan_next_tasks`'s accept-and-merge success path is covered:
  `test_plan_next_tasks_accepts_and_merges_a_valid_plan` in test_swarm.py uses `PlanningAdapter`
  with `verify="exit 0"` and asserts the planner returns `status="planned"` and the planned tasks
  merged into the repo's docs/STATUS.md — the full plan-accepted/commit/merge path. No production change.

- `cmd_swarm`'s continuous-mode output is covered:
  `test_swarm_cli_continuous_prints_round_summary` in test_swarm.py stubs `run_continuous_swarm`
  to return a result with rounds/plans and runs `swarm --headless --continuous`, asserting the
  "continuous · N rounds · M plans" summary is printed. No production change.

- `run_continuous_swarm`'s max-rounds-with-no-work exit is covered:
  `test_continuous_swarm_returns_at_max_rounds_with_no_work` in test_swarm.py runs it with
  `max_rounds=1` in a repo with all tasks done and asserts it returns after the single empty round
  (`rounds == 1`) rather than planning. No production change.

- `run_continuous_swarm`'s top-level-error exit is covered:
  `test_continuous_swarm_returns_on_top_level_error` in test_swarm.py stubs `run_swarm` to return
  an errored `SwarmResult` and asserts `run_continuous_swarm` returns `reason == REASON_ERROR`
  carrying that error. No production change.

- `run_continuous_swarm`'s planner-failure exit is covered:
  `test_continuous_swarm_returns_on_planner_failure` in test_swarm.py (work exhausted,
  generate_ideas) stubs `plan_next_tasks` to fail and asserts `run_continuous_swarm` returns
  `reason == REASON_ERROR` carrying the planner error. No production change.

- BUG FIX: the continuous-swarm `--limit-max-resumes` cap was ineffective for a *persistent
  planner* usage-limit — an unbounded loop. `limit_attempt` was reset unconditionally each round
  (swarm.py), so every no-work round cleared the counter before the planner-limit cap could trip;
  a perpetual planner limit looped forever, contradicting the documented bound. Fixed by resetting
  `limit_attempt` only on a productive round (inside `if result.workers`). Found by a hanging test;
  covered by `test_continuous_swarm_planner_limit_persists_to_terminal` (asserts `REASON_LIMIT`),
  with the worker-limit resume tests still green.

- The planner's git-status inspection-failure path is covered:
  `test_plan_next_tasks_fails_on_git_status_inspection_failure` in test_swarm.py wraps `_git` so the
  planner's `status` call fails and asserts `plan_next_tasks` returns `status="failed"` carrying the
  inspection error — a git failure during planning is a clean failure, not a crash. No production change.

- The planner's git-diff inspection-failure path is covered:
  `test_plan_next_tasks_fails_on_git_diff_inspection_failure` in test_swarm.py wraps `_git` so the
  planner's `diff` call fails and asserts `plan_next_tasks` returns `status="failed"` carrying the
  diff-inspection error. No production change.

- The planner's git-commit-failure path is covered:
  `test_plan_next_tasks_fails_when_planner_commit_fails` in test_swarm.py wraps `_git` so the
  planner's `commit` fails after a valid plan and asserts `plan_next_tasks` returns `status="failed"`
  carrying the commit error. No production change.

- The planner's merge-to-root conflict-abort path is covered:
  `test_plan_next_tasks_fails_when_merge_to_root_conflicts` in test_swarm.py wraps `_git` so the
  planner's `merge --no-commit` fails and asserts `plan_next_tasks` returns `status="failed"`
  carrying the conflict error, never leaving a half-merged tree. No production change.

- The swarm worker git-commit-failure path is covered:
  `test_swarm_fails_worker_when_commit_fails` in test_swarm.py wraps `_git` so the worker's
  `looptight:` commit fails and asserts the worker is `failed` with the commit error, not integrated.
  No production change.

- The swarm worker git-status inspection-failure path is covered:
  `test_swarm_fails_worker_when_status_inspection_fails` in test_swarm.py wraps `_git` to fail the
  worker's `status --porcelain` (only in the worker worktree, not the invoking-worktree cleanliness
  check) and asserts the worker is `failed` with the inspection error. No production change.

- `swarm._integrate` (the no-coordinator direct-merge fallback) is marked `# pragma: no cover`
  with a comment, consistent with its sole caller (the `if coordinator is None` branch, already
  no-cover). A swarm requires a clean Git worktree so the coordinator is never None and the durable
  Integrator path is always taken; the fallback body is unreachable in normal runs. The misleading
  coverage signal that pointed at unreachable code is gone (swarm.py coverage now reads honestly),
  the defensive fallback is kept, and the swarm tests stay green. No behavior change.

- The usage.md empty-queue example shows `looptight next --no-ideas --json` so its bare
  `{"status": "no_work", "task": null}` output matches the command: the default (`idea_generation`
  on, tasks.py:190-192) carries a `generate_ideas` directive, which the snippet would otherwise
  contradict. A `test_docs.py` assertion locks that any bare-`no_work` example uses `--no-ideas`.

- The usage.md `next --json` task example shows the always-present `idea_id` and
  `suggested_verify` keys (tasks.py:151,157), so it teaches the full task contract rather than a
  narrower shape. A `test_docs.py` assertion locks both keys into the doc.

- `next` refuses outside a Git repository like `doctor`, `status`, and `verify`, instead of
  treating a non-repo as an empty clean queue and emitting a `generate_ideas` directive (which
  would drive a host session to build into a directory with no checkpoints or claim coordinator).
  The guard lives at the command boundary (`cmd_next`, protocol_commands.py) where siblings check
  and where the bug manifests, keeping `next_task` usable as a non-git unit harness: a non-repo
  yields `{"status": "error", "error": "not_git"}` and CLI exit 2. Covered by a CLI test; the
  in-Git path is unchanged.

- `init` creates a one-line `.gitignore` (`__pycache__/`) when it sets a Python verify and no
  `.gitignore` exists, so the out-of-box pytest loop no longer stalls: previously the first
  `verify` left untracked `__pycache__/` and the next `next` refused the dirty worktree. It never
  rewrites an existing user `.gitignore` (init owns only files it creates), and the dirty-worktree
  gate is unchanged. Two CLI tests cover the create-when-absent and leave-existing-untouched paths.

- A corrupt, locked-out, or newer-schema coordinator DB no longer crashes every read command with
  a traceback. `Coordinator.open` (coordinator.py) converts an unusable DB into a dedicated
  `CoordinatorUnavailable` with an actionable message (DB path + remedy), and the cli.py top-level
  handler catches it like `ConfigError`: a structured `{"status":"error","error":
  "coordinator_unavailable"}` envelope under `--json`, a clean message otherwise, both exit 2 with
  no traceback. Covered by coordinator-level (corrupt + newer-schema) and CLI-level tests.

- Curated `## Next` / task-file task text is bounded by a generous `_MAX_TASK_TEXT` (4000) cap,
  closing the gap where `from_task_file` set `title`/`detail`/`acceptance` uncapped while TODO/lint
  markers were already bounded to 200. A pasted multi-hundred-KB curated line can no longer become a
  giant `goal`/`evidence` that floods host-agent context; normal paragraph-length tasks are
  untouched. `_bound` now takes a `limit` param (default unchanged). Covered by a `test_propose.py`
  test.

- The top-level `ConfigError` handler honors `--json`: a malformed `.looptight.toml` now yields a
  parseable `{"status":"error","error":"config_error"}` envelope on machine-facing commands
  (status/doctor/next/propose) instead of a plain-text `config error:` line that broke JSON
  consumers, and the human path still prints the readable message. Shares a `_emit_json_error`
  helper with the `coordinator_unavailable` handler so both contracts match. Covered by a CLI test.

- `load_config` rejects recognized config keys nested under a TOML table (e.g. a `[policy]`
  table holding `max_changed_files`/`protected_paths`) with a clear `ConfigError`, instead of
  silently dropping them — a footgun for safety-relevant settings the user believed they set, made
  tempting because `status --json` reports a `policy` object. An unknown table with no recognized
  keys is still ignored (forward-compatible). Covered by reject + ignore tests in test_config.py.

- `propose`'s no-candidates message no longer claims "(clean tree)": the line speaks to task
  signals, not git state, so it now reads "No candidate tasks found from repo signals." and cannot
  mislabel a worktree with untracked files (which `revert` correctly reports in place) as clean.
  Covered by a CLI test alongside the existing `--source` clean-tree guard.

- `cmd_goal` validates before storing a goal: it refuses outside a Git repository (`not_git`) and
  rejects an empty/whitespace vision (`empty_vision`) with a clean error — a JSON envelope under
  `--json`, a message otherwise, exit 2 — instead of crashing with an uncaught `RuntimeError`
  traceback (non-git) or persisting a vacuous goal that hands the host an empty build directive.
  Brings goal-set in line with how `next` and the other goal actions already handle these. Covered
  by two CLI tests.

- `score_status_next` now scores the RAW generated `## Next` batch (`from_status_next` gained
  an `enforce_truthful_evidence` param, default True for the next/propose claim path; the eval
  passes False), so `score_batch`'s own grounding check measures it: `size`/`bounded` reflect the
  true count and `groundedness` is an honest fraction, not a constant 1.0. Previously the batch
  was grounding-filtered before scoring, hiding over-generation and fabricated evidence from the
  `current_quality` feedback; `propose --eval` now surfaces a fabricated item instead of dropping
  it. Covered by an idea_eval test; the `propose --eval` CLI test updated to the corrected behavior.

- Python skipped-test candidates in one file no longer collide to a single `idea_id`: the
  candidate title now names the enclosing test (`_enclosing_test_name` finds the `def` above an
  imperative skip or below a decorator skip), so sibling skips stay distinct ideas — cooldown
  can't suppress an innocent sibling and outcome stats don't merge. A module-level `pytestmark`
  with no enclosing function keeps the file-level title (one idea). Covered by a test_propose test.

- `recent_failures` counts only in-window failures: the SQL query now uses `AND created_at >= :cutoff`
  in the WHERE clause so `COUNT(*)` is bounded to the window — an idea that failed once long ago and
  once recently reports count 1, not 2, matching the documented "recent failures reached the threshold"
  contract. The Python-side `MAX(created_at)` filter is superseded by the SQL gate.
  Covered by `test_recent_failures_counts_only_in_window_failures` in test_coordinator.py;
  existing windowed and outside-window tests unchanged.

- `_verifier_quality` no longer misclassifies `pytest -m "not playwright"` / `pytest -m "not
  cypress"` as `e2e`: `scan` now also strips `not playwright` and `not cypress` before the e2e
  check, so a command *excluding* those test markers classifies as `unit` instead. Real `playwright
  test`/`cypress run` commands still classify as `e2e`; behavior of `not integration`/`not e2e`
  is unchanged. Symmetric fix to the existing `not integration`/`not e2e` case.
  Covered by the extended `test_status_json_ignores_negated_marker_deselection` in test_cli.py.

- `_has_dirty_git_worktree` (tasks.py) passes `GIT_TERMINAL_PROMPT=0` to its `git status`
  call, so a headless `looptight next` can't block on a git credential prompt — part of the
  uniform non-interactive-git invariant. Covered by a test_tasks.py env assertion.

- `_changed_entries` (`git status --short`) and `_git_common_dir` (`git rev-parse`) in
  protocol_commands.py pass `GIT_TERMINAL_PROMPT=0`, extending the non-interactive-git
  invariant to the `looptight status` path. Covered by two test_cli.py env assertions.

- `coordinator_path` (`git rev-parse --git-common-dir`) passes `GIT_TERMINAL_PROMPT=0`,
  completing the uniform non-interactive-git invariant across the session-native call sites
  (next/status/goal all open the coordinator). Covered by a test_coordinator.py env assertion.

- The integration crash-reconcile re-apply path is lease-fenced: `_reconcile_one`'s
  nothing-committed branch now finishes `superseded` (via a shared `_superseded` helper used by
  `_run`) when the lease was reaped+reclaimed by a newer owner/generation, instead of re-merging
  and committing a stale candidate under a lease it no longer owns. Closes a durability hole
  where the same task could double-apply across sessions; single-session crash recovery (lease
  still owned) still re-applies. Covered by a reap+reclaim reconcile test.

- `persistent_from_sets` ignores unparseable (empty) failure-set iterations in its
  intersection, so one noise iteration (timeout / unrecognized output) no longer erases a
  failure that held across every meaningful try from the escalation evidence. Evidence-only;
  the stop/escalate decision in `assess` is untouched. Covered by a metacog test; the
  keeps-only-what-cleared / no-overlap / nothing-parses cases are unchanged.

- The daemon's idle/stall backoff is no longer defeated by an early merge: `_outcome`
  classifies `progress` (delay 0) only for a draining `REASON_ERROR` (some merged, no top-level
  error); `NO_WORK`/`IDLE`/`LIMIT` map to `idle` regardless of cumulative merges, so a stalled
  swarm or drained backlog polls after `idle_sleep_seconds` instead of re-attacking a
  degenerate planner state with no delay (a model-call-burning loop). Covered by a direct
  `_outcome` test; two tests that used `REASON_IDLE+merged` as the progress example now use the
  genuine `REASON_ERROR`-draining case.

- The daemon forwards its interruptible `sleep` into `run_continuous_swarm`, so the swarm's
  internal usage-limit waits also abort promptly on SIGTERM/SIGINT. Previously only the
  between-cycle delay used it; the swarm's waits used the default `time.sleep`, which PEP 475
  lets run to completion on a signal, so shutdown could hang up to `limit_max_wait_seconds`
  (3600s) per attempt despite `cmd_daemon`'s ~1s claim. Covered by a sleep-forwarding test.

- Integration crash recovery between commit and ref-advance is worktree-independent: `_apply`
  persists the merge `result_sha` and sets state `committed` (new `mark_integration_committed`)
  before the ref advance, `IntegrationRecord`/`integrating_records` carry it, and `_reconcile_one`
  advances the ref from the durable `result_sha` before falling back to the worktree. So a later
  integration resetting the shared per-ref worktree no longer forces a wasteful re-merge on
  recovery, and the previously-dead `committed` state is now used. Covered by a worktree-reset
  recovery test; the parametrized crash-recovery suite stays green.

- `run_command` redirects agent-CLI stdin from `/dev/null` on both branches, so a headless
  invocation can't hang forever on a credential prompt or interactive confirmation by inheriting
  looptight's stdin (headless agents take their prompt via argv, never stdin). Universal
  headless-safety fix on every path, not just the swarm path that already had a timeout.
  Covered by a both-branches stdin=DEVNULL test.

- The `ui` loopback server validates the `Host` header (`_host_is_loopback`), returning 403 to
  any request whose Host is not a loopback name (`127.0.0.1`/`localhost`/`::1`, with or without
  a port; an absent Host is allowed for direct tools). This blocks DNS rebinding, where a remote
  page rebinds its domain to 127.0.0.1 and reads the read-only repo state through a victim's
  browser. Covered by `_host_is_loopback` unit cases and a non-loopback `do_GET` 403 test.

- The `ui` tally is a coherent task-centric partition: a tested server-side `summarize(state)`
  computes `total` = number of tasks with active/attention/complete as subsets of those tasks,
  exposed on `/api/state`, and the page renders `state.summary` instead of recomputing it
  inconsistently (it had mixed tasks-for-total with tasks+workers-for-breakdown, so 4 total sat
  beside 2/2/2 over 7 nodes). The strip now reads e.g. 4 / 1 / 1 / 1. Covered by summarize unit
  tests + the /api/state contract test; workers stay visible in the graph.

- The `ui` page serves an on-brand SVG `/favicon.ico` (the wordmark's loop-ring + cycle-arrow +
  verify-check glyph in acid green) and declares `<link rel="icon">` in <head>, so the browser's
  implicit favicon probe no longer 404s on every load (the page now renders with zero console
  errors) and the tab carries a looptight mark. Same-origin, CSP-clean. Covered by a do_GET
  favicon test.

- The `ui` task node surfaces the task `source` (provenance: todo/lint/status-next/...) as its
  detail line instead of the opaque internal id, so the graph and inspector show where each task
  came from. The `source` field was already written to state by the swarm but never displayed.
  Wire ids are unchanged. Guarded by a render() page assertion.

- Loop-control lever 1 (smart stop-gate): the Stop hook now carries a session through the
  grounded backlog when opted in. With `continue_through_backlog = true`, a *passing* verify no
  longer always ends the turn — `decide` blocks with a `looptight next` directive while claimable
  grounded work remains (probed read-only via `propose`, no claim), under the iteration cap, and
  allows an honest stop once `propose` is dry. It deliberately does not force on the bare
  generate_ideas directive (the busywork trap). Default off preserves verify-until-green. Covered
  by `decide` unit tests (continue / honest-stop / opt-in-off / cap), `run_hook` integration with a
  stubbed work probe, and a config round-trip. Lever 2 (drift directive) is next.

- Loop-control lever 2 (drift directive): under the `continue_through_backlog` opt-in, the Stop
  hook refocuses a session that has wandered off its claimed task. `Coordinator.active_lease_for_owner`
  reads the owner's live lease (with payload), and a conservative pure `_off_task` flags drift only
  when the uncommitted diff (`git diff HEAD`) is wholly unrelated to the task's evidence — a change
  is on-task if it is the evidence file or shares its stem, so a normal source+test edit never
  trips it (directory is deliberately not scope, since a flat layout would never drift). On drift
  the hook blocks with a refocus directive (priority over backlog continuation); on-task or opt-in
  off, nothing changes. Verified end-to-end on the live repo. Covered by coordinator, `_off_task`,
  and `run_hook` tests. Both loop-control levers (smart stop-gate + drift) are now built.

- docs/usage.md now documents the hands-off Stop-hook loop: a "Hands-off loop (Stop hook)"
  subsection covers `install-hook`, the verify-until-green default (no model call, dormant
  without a verify command), and the `continue_through_backlog` opt-in (continue through the
  grounded backlog, honest stop at NO_WORK, never forcing idea generation, refocus on drift); the
  `.looptight.toml` example carries the flag. A `test_docs.py` assertion locks both into the doc.

- A `ui` worker node now reads as what it's building: render() looks the linked task's goal up
  from `state.tasks` by `task_id`, so a no-error worker shows e.g. "Harden the verifier..."
  instead of the opaque 12-hex id (error still wins when present, id is the last fallback). No
  more tracing the wire to the task node to see what a worker is doing. Verified live; guarded by
  a render() page assertion.

- The README's "What it can do" surfaces the hands-off Stop-hook loop (`install-hook`): a
  bullet covers verify-until-green and the `continue_through_backlog` opt-in (carry the session
  through the grounded backlog, honest stop at NO_WORK) and links to the usage.md section, so the
  capability appears on the project front page like the other modes. Locked by a test_docs assertion.

- `looptight ui` now represents the default session-native loop, not just the swarm: when no
  swarm state is published, the `/api/state` handler overlays the owner's active coordinator
  claim (`_with_session_task` → `active_lease_for_owner`) as a single `claimed` task with
  manager status "session", so the page shows what you're working on instead of a misleading
  "idle". A live swarm state is left untouched; any coordinator error degrades to idle. Read-side
  only — the session-native path is unchanged. Verified live; covered by overlay/no-overlay/idle
  unit tests.

- `looptight statusline` represents the default session-native loop, parallel to the ui: when
  there are no swarm workers it now shows the current task's goal (`looptight: <task>`,
  truncated) instead of "idle", and `cmd_statusline` overlays the session claim via
  `_with_session_task`. Swarm mode (workers present) is unchanged; truly-empty stays "idle".
  Covered by statusline session/swarm/idle unit tests.

- The `ui` manager node is mode-aware: in session mode (the overlaid session claim) it reads
  "session" / "your next / verify loop" instead of the swarm "orchestrator" /
  "deterministic integration gate", so a single next/verify session is no longer misrepresented
  as a swarm orchestrator running an integration gate. Swarm mode is unchanged. Verified live;
  guarded by a render() page assertion.

- `looptight status` names the claimed task by its goal, not its opaque fingerprint: the
  next-action now reads "continue your claimed task: <goal>" (pulled from the lease via
  `active_lease_for_owner`), falling back to the fingerprint when the goal is unavailable. The
  machine-stable `claimed_task` JSON field is unchanged. Completes the show-the-goal-not-the-id
  thread across the ui, statusline, and status. Covered by a CLI test.

- The `ui` session view is structurally a session, not a swarm: render() toggles a `session`
  class on the graph in session mode, and the stylesheet drops to two columns and hides the
  swarm workers lane — so the page shows just manager → claimed task, no empty "no workers"
  column. Completes the swarm-framing fix started on the manager node; swarm mode keeps all three
  lanes. Verified live; guarded by page/stylesheet assertions.

- The `ui` session view shows the loop's key signal — the last verify verdict — beside the
  claimed task: `cmd_verify` records the verdict (guarded `write_verdict`, a small atomic JSON
  sidecar, consistent with verify already persisting trajectory state), and `_with_session_task`
  reads it so the session manager detail reads "your next / verify loop · verify: pass". Swarm
  mode and the machine verify contract are unchanged; a missing/corrupt verdict degrades to no
  badge. Verified live (`manager: session, verify: pass`). Covered by round-trip, overlay, page,
  and verify-CLI tests. (Design choice — verify persisting a verdict — flagged for review.)

- The `ui` session view's footer shows the verify freshness instead of UNKNOWN: a shared
  `_verdict_record` reader lets `_with_session_task` set the synthesized state's `updated_at` to
  the verdict's `at` timestamp, so the footer reads "LAST EVENT 2M AGO". `read_verdict` still
  returns the status; a missing/corrupt verdict degrades to no badge and UNKNOWN. No new write;
  swarm mode unchanged. The session view now fully represents the default loop: task, mode,
  verdict, and freshness.

- `looptight ui` now represents goal mode too, completing all three loop modes (swarm, session,
  goal): when no swarm state and no session claim exist but a build goal is active,
  `_with_session_task` overlays it (manager status "goal", a node showing the vision with
  "goal · iteration N"), and render() frames the "goal" manager mode ("your goal build loop")
  with the same two-lane layout as session mode. A session claim takes precedence over a goal;
  read-only (reuses `read_goal`), degrades to idle on any error. Verified live; covered by
  `_active_goal_view`, overlay-precedence, and page tests.

- `looptight status` names an active goal by its vision: the next-action reads "run `looptight
  goal next` (building: <vision>)" (truncated) instead of the generic "a build goal is active",
  reusing the goal it already reads. Completes the show-the-goal thread across status / statusline
  / ui for all three loop modes (claimed task, swarm worker, goal vision). Covered by a CLI test.

- A publication no longer strands on a transient remote-move: `_publish` re-fetches and retries
  the exact-SHA, non-force push up to `_MAX_PUSH_ATTEMPTS` (3) — recovering when the remote moved
  between fetch and push (CI / another session), or when the re-fetch shows the result is now an
  ancestor — then fails as before if still rejected. Never forces, never replays the candidate;
  `begin_publication` keeps the first observed tip. Covered by recover-on-transient and
  bounded-retry-then-fail tests. (Design choice — auto-retry vs strand — documented for review.)

- The verify trajectory no longer bleeds across tasks: it is keyed on the claimed task (the
  active claim's idea id) as well as (worktree, command), so a second task that reuses the
  repo's constant verify command starts a fresh trajectory instead of inheriting a prior
  abandoned task's signal history (which could wrongly stall it on its first verify under
  `--patience`). `_stall_signal` reads the task via `active_lease_for_owner` (read-only, degrades
  to None — no regression for the no-claim case); the stall DECISION is unchanged, only the
  trajectory's scope. Within the metacog `--patience` subsystem; the core verify path is
  untouched. Covered by a changed-task reset test. (Design choice — scope by claim idea id —
  documented for review.)

- The `ui` idle guide now leads with the primary loop: "Idle — claim a task with `looptight
  next`" instead of "start a swarm", aligning the empty-state guidance with the default loop the
  view now represents (and with the README, which leads with `next`). Swarm stays discoverable in
  the docs. Covered by the idle-state guidance test.

- The usage.md "Local view" section reflects the multi-mode views: it now says `status`/`ui`/
  `statusline` show your current loop — the claimed task and last verify result on the default
  `next` loop, the vision in goal mode, or the swarm's workers — instead of describing them as
  swarm-only, and the statusline example shows a session-mode line. Matches the ui/statusline/
  status session+goal representation shipped this session. Locked by a test_docs assertion.

- `status --watch` and the terminal status panel represent the session/goal loop, not just the
  swarm: `render_state_panel` now renders a one-line session/goal summary (`session: <goal> ·
  verify: pass`) when there are no workers but a claim/goal is overlaid, and both `status` panel
  sites overlay state via `_with_session_task` (parallel to `cmd_statusline`); the empty fallback
  reads "idle — run looptight next" instead of "swarm: no active workers". Swarm mode unchanged.
  Verified live. This completes the multi-mode representation across all surfaces: browser ui,
  statusline, status, and the --watch panel.

- The statusline appends the last verify verdict in session mode ("looptight: <task> · pass" /
  "· fail"), so the always-visible status bar shows whether your last gate passed — the verdict
  is now consistent across all four surfaces (browser ui, --watch panel, status, statusline).
  No verdict / no overlay is unchanged; swarm worker tally is unchanged. Covered by a statusline
  test.

- The goal-mode overlay now carries the verify verdict and freshness like the session
  overlay, through one shared `_solo_overlay` helper (ui.py); the browser ui goal-mode
  manager detail appends "· verify: pass"/"· fail" when a verdict exists. Goal-mode build
  increments are verify-gated, so this is the goal's build-health signal — the verdict is
  now consistent across both solo modes on every surface. No verdict / swarm mode unchanged.
  Covered by goal-overlay and goal-detail tests.

- The tally now buckets every real swarm status: `verified` (passed verify, awaiting merge)
  joins `active`, and `limited` (hit a usage cap) / `interrupted` join `attention`, in both
  the Python `_STATUS_GROUPS` and the mirrored JS `groups` set. Previously a task in any of
  those states counted toward `total` but no bucket, so `active + attention + complete` was
  silently less than `total` and the filter buttons disagreed with the tally. Found by
  dogfooding the ui with a swarm state. Covered by a status-coverage test and a
  groups-in-sync test.

- The graph node border colors now match the tally legend: active task statuses render with
  the acid border (was cyan, indistinguishable from complete and contradicting the acid
  manager), complete statuses cyan, and attention statuses — now including `limited` and
  `interrupted` — red (border and badge). Confirmed by dogfooding: a `claimed`/`integrating`
  task and a `limited` worker now read acid/red instead of cyan/amber. The graph and tally
  share one color language across all status groups. Covered by a border-legend test and a
  badge test.

- A failing solo-mode verdict now reads red instead of muted gray: when the overlaid
  `manager.verify` is present and not "pass", the manager node gets a `verify-fail` class and
  its detail ("… · verify: fail") renders in the attention color, so a broken gate is legible
  at a glance. The pass case is untouched (stays muted). Confirmed by dogfooding goal mode:
  the detail computed color is now red. Covered by a page test.

- The Local view docs now reflect the verdict work: they state the verify result shows in
  both the default loop and goal mode (in red when it failed), and the statusline example
  shows the appended `· pass`/`· fail` suffix. Keeps the docs honest about what each surface
  shows. Covered by a strengthened test_docs assertion.

- `doctor` now explains its readiness verdict inline: after `readiness: <tier> (exit N)` it
  prints a `readiness checks:` line with the reasons (verify/git/coordinator/task_sources/
  agent), the same breakdown `status` shows, so the diagnostic is self-contained instead of
  labelling readiness `unsafe` with no explanation. Found by dogfooding a fresh repo. Covered
  by a test_cli assertion.

- The `next` human output no longer doubles the evidence label: it prints the bare parsed
  anchors under a single `evidence:` label (`evidence: src/m.py:1`), matching the clean
  `acceptance:` line, instead of repeating the stored marker. Render-only via `evidence_refs`
  with a raw fallback for ad-hoc (markerless) evidence; the stored field and the parsers are
  untouched. Found by dogfooding `next`. Covered by a stutter test and a fallback test.

- Goal-mode static `status` no longer prints the vision twice: the overlay panel (which
  duplicated the dedicated `goal:` line) is suppressed when a goal is active, and the last
  verify verdict is folded onto the dedicated goal line so build health stays visible
  (`goal: <vision> (iteration N) · verify: pass`). The panel is unchanged for swarm/session,
  and `--watch` (panel-only) was never affected. Found by dogfooding. Covered by a test
  asserting one goal line carrying the verdict.

- `status` no longer prints the same next-step under two labels: the human `readiness next:`
  line is suppressed when its remediation equals the authoritative `next:` action (the ready
  and dirty-worktree states, where both resolved to the identical string). It is still shown
  when readiness needs a distinct step (e.g. goal mode: `add grounded tasks` vs `run goal
  next`). JSON `next_remediation` is unchanged. Found by the data-representation audit and
  confirmed by dogfooding. Covered by a dedup test and a distinct-step test.

- `VerifyResult.short()` now reflects the real verdict (PASS/FAIL/TIMEOUT/ERROR) instead of
  collapsing every non-pass to FAIL, so a timeout no longer prints `verify: FAIL` above
  `verifier result: timeout`. The honest label reaches all six surfaces (verify command,
  run-loop record, stop-hook/continuation messages, summary). PASS/FAIL with the optional
  score suffix are unchanged. Found by the data-representation audit. Covered by a
  timeout/error short() test.

- The tally cells are now one coherent legend with the graph: `total` reads neutral
  (`var(--line)`), `active` acid, `attention` red, `complete` cyan. Previously the `.stat`
  default was acid and there was no `.stat.active` rule, so the neutral total count wore the
  active color. Found by the data-representation audit. Covered by a tally-legend test.

- The terminal worker tally now reads in the same count-status order on both surfaces: the
  `--watch`/`status` panel renders "workers: N (1 running, 1 merged)" to match the
  statusline's "1 running · 1 merged" (was inverted to "running 1"). Found by the
  data-representation audit. Covered by the panel and watch-status tests.

- Goal-mode human `status` names the vision once: the redundant `(building: <vision>)`
  parenthetical is stripped from the human `next:` line (the dedicated `goal:` line above
  already shows it), leaving `next: run \`looptight goal next\``. The action string and the
  JSON `next_action` contract still carry the vision for machine consumers. Found by the
  data-representation audit. Covered by a human-dedup + JSON-contract test.

- The terminal panel's worker error now signals truncation with a trailing `...` (matching the
  goal truncation), so a long error is no longer cut mid-string and read as the complete
  message — the operator can tell the cause was clipped. Short errors are shown verbatim.
  Found by the edge-state representation audit. Covered by a truncation-signal test.

- Safe-by-default badges: a task/worker whose status is outside the known set now renders a
  neutral (muted) badge instead of the green "healthy" one. `node()` tags an out-of-group,
  non-manager status with `unknown-status` (reusing the existing JS `groups`, no new status
  list) and a `.unknown-status .status` rule mutes it. Guards against a corrupt state or a
  future status added to the swarm but not the groups looking successful. Confirmed by
  dogfooding (a `frobnicate` status computes a muted badge; `running` stays acid). Found by
  the edge-state audit. Covered by a page test.

- A worker missing its `number` now reads as unknown rather than a literal None/undefined:
  the terminal panel shows `#?` (was `#None`) and the browser node title shows `worker ?`
  (was `worker undefined`). Small defensive fallback on a malformed/corrupt state. Found by
  the edge-state audit. Covered by a missing-number test.

- The status panel no longer eats user bracket-tokens: a new `Console.write()` prints
  already-rendered content verbatim (no markup stripping), and `status` / `status --watch`
  use it for the panel. A worker error like `tool said [red] then died` now survives instead
  of becoming `tool said  then died`. The markup-template paths (`Console.print`) are
  unchanged. Found by the edge-state audit. Covered by a Console.write unit test and a
  status-panel behavioral test.

- The remaining pure-user-content human lines now print verbatim via `Console.write`: the
  propose candidate title, the status goal line, and the `goal status` / `goal set` echoes.
  A task title like "Fix the [red] badge" or a vision naming a `[dim]` section keeps its
  token instead of having it stripped. Markup-bearing lines stay on `console.print`. Found by
  the edge-state audit. Covered by propose-title and goal-vision token tests.

- The browser UI's two `aria-live` regions no longer re-announce on every 1.5s poll: `tally()`
  early-returns on an unchanged `lastTallyKey`, and the poll-time inspector re-render is
  guarded by `lastInspectorKey`, so a screen reader hears the tally/details only on a real
  change (user clicks still update immediately). Found by the accessibility audit. Covered by
  a live-region change-detection test (empirical browser confirmation was blocked by browser
  flakiness this session; the logic is unit-tested and verify-gated).

- Three a11y semantics fixes: the connection status is now a `role=status aria-live=polite`
  region whose text is set only on change, so a screen reader learns when the backend goes
  away without per-poll spam; the node `aria-label` falls back to `status unknown` instead of
  emitting the literal `undefined`; and the `.filter` buttons get a visible `:focus-visible`
  outline matching the nodes. Found by the accessibility audit. Covered by a semantics test.

- Card/stat/filter/node borders now meet WCAG 1.4.11: `--line` was lightened from `#405047`
  (2.13:1 on `--panel`) to `#5a6f63` (3.37:1), and the wire arrow-marker fill tracks it. The
  border is the sole boundary cue (fill/shadow are imperceptible), so low-vision users can now
  perceive where cards begin. Found by the accessibility audit. Covered by a test that computes
  the WCAG contrast ratio from the page's hex values.

- The three graph lanes now announce as labeled regions: each `.lane` has `role=group` and
  `aria-labelledby` pointing at its (now id'd) title, so screen-reader users get the
  manager/tasks/workers structure to navigate. Purely additive markup, no visual change.
  Found by the accessibility audit. Covered by a lane-labeling test.

- The smallest UI text (`.eyebrow`, `.stat span`, `.status`, `.filter`) is bumped from 10px to
  11px for readability, while the 10px spacing values are untouched. A small low-risk
  improvement the a11y audit flagged. Covered by a font-size test.

- Three human-output lines now use proper singular/plural instead of the lazy `(s)`: the
  revert untracked-files note, the uninstall-hook count ("1 looptight hook" / "2 hooks"), and
  the status idea-quality line ("1 task" / "2 tasks"). Consistent with the codebase's existing
  pluralization (propose). Covered by idea-quality and uninstall plural tests.

- The swarm command output now reads correctly: a `_plural(n, word)` helper gives proper
  agreement ("1 worker" / "2 workers", "1 plan", "max 1 round") across the banner, tally, and
  continuous summary, and `_swarm_tally` uses the count-status order ("1 merged") matching the
  ui panel and statusline — completing that consistency across every tally surface. Covered by
  the updated swarm tally/banner/continuous tests.

## Next

1. `propose --json` emits pretty-printed `indent=2` output (`src/looptight/protocol_commands.py:212`)
   while every other `--json` command emits compact `sort_keys=True` — the lone formatting outlier,
   with no rationale comment and no test pinning the whitespace (the propose JSON tests parse with
   `json.loads`). Make it compact `sort_keys=True` so tooling gets uniform machine output across all
   commands; the data structure (a candidates list / `{candidates, eval}`) and ranking order are
   unchanged.
   Evidence: src/looptight/protocol_commands.py:212
   Acceptance: a new test asserts `propose --json` output is a single line (no `indent` newlines)
   and still parses to the same candidate list.

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
