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

## Next

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
