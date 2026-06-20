# Review Queue

Items blocked on unavailable evidence or a decision that cannot be derived
safely from the repository. Autonomous runs skip these and continue with the
next actionable task.

---

## AUDIT (2026-06-20, eleventh)

Reviewer: independent checker agent. Previous AUDIT marker: `02973c4` (tenth audit).
Reviewed 9 commits from `43281b8` through `185c67c`.

### Test and lint gate

`uv run pytest`: 250 passed, 1 skipped (env-gated e2e — correct). Up from 229 in the tenth audit.
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `43281b8` | docs: record idle improve run 2026-06-20 (eleventh; no actionable work) |
| `f23dbb4` | docs: focus v0.2 on session-native protocol |
| `515bfc9` | feat: make validation verdicts machine-readable |
| `a748952` | feat: add grounded next task protocol |
| `8d4f78f` | docs: bound the self-improvement plan |
| `2b47783` | feat: claim tasks across worktrees |
| `65d9c6f` | feat: install native session loop instructions |
| `90e766b` | feat: add read-only loop status |
| `185c67c` | feat: require explicit headless agent spawning |

### Verdict: clean with one minor concern

**`43281b8` / `8d4f78f`** — Docs only. No concerns.

**`f23dbb4`** — Large SPEC.md rewrite and deletion of stale plan docs from
`docs/plans/` and `docs/specs/`. One-line propose.py comment update pointing to
the new SPEC.md location. Tightens scope; no concerns.

**`515bfc9`** — Machine-readable `--json` for `looptight verify`. Good design:
`VerifyResult.__post_init__` invariant (`passed == (exit_code == 0)`) holds in all
three paths (timeout exit 124, launch-error exit 127, normal). `_verify_exit_code()`
correctly distinguishes tool errors (exit 2) from code failures (exit 1). `ConfigError`
caught inside `cmd_verify` so a malformed config emits a clean JSON error rather than
crashing. Tests cover the JSON contract. No concerns.

**`a748952`** — Refactors `next_task()` from raw string to structured `NextResult`.
Removes the fallback to `_audit_goal` (which could generate unprompted self-improvement
work in an autonomous session); replaces with explicit `no_work`. SHA-256 task ID
(12-hex prefix) for stable identity across calls. Tests cover both code paths and the
stable JSON contract. No concerns.

**`2b47783`** — Adds `claims.py` for atomic task coordination across worktrees.
`O_EXCL` prevents double-claiming; 24h stale threshold; `limit=0` in `propose_fn`
correctly returns all candidates (confirmed: `propose.py:318`). Tests cover atomic
claims, stale expiry, cross-task cleanup, and the non-mutating `summary()` method.
No concerns.

**`65d9c6f`** — Adds `integration.py` with idempotent managed-block pattern for
AGENTS.md and CLAUDE.md. `--integrate` flag on `looptight init` keeps session
instructions an explicit opt-in. Idempotency and surrounding-content preservation
are tested. No concerns.

**`90e766b`** — Read-only `looptight status` command reporting verify config, git
workspace state, and claim state. No side effects. One minor inconsistency noted
(see concern below).

**`185c67c`** — Adds `--headless` guard to `looptight run` and `looptight improve`
to prevent accidental child-agent spawning from within an autonomous session. Breaking
change for existing users (add `--headless`), acceptable at v0.1 given the protocol
shift to session-native. Tests updated correctly. The `--headless` in the `--help`
test is unnecessary but harmless. No concerns.

### Minor concern (flag, do not revert)

`cmd_status --json` does not catch `ConfigError` internally. A malformed
`.looptight.toml` causes the top-level handler in `main()` (cli.py:194) to emit a
human-readable message rather than a JSON error object. `cmd_verify --json` handles
this correctly. Suggested fix: wrap `load_config()` in `cmd_status` in a
`try/except ConfigError` and emit a JSON error payload analogous to `cmd_verify`.

---

## IMPROVE RUN (2026-06-20, eleventh) — idle, no changes

Setup: `uv venv` + `uv pip install -e ".[dev]"`; `uv run pytest -q` → 229 passed,
1 skipped (env-gated e2e — correct); `uv run ruff check` → clean. **Main is GREEN.**

**No code changes this run.** `uv run looptight propose` reported "No candidate
tasks found from repo signals (clean tree)." Scanned `src/` for TODO/FIXME/HACK/XXX
(none) and reviewed the standing REVIEW-QUEUE escalations — all remain legitimate
non-goals that cannot be verified offline (Codex `/goal` self-grading, real-CLI JSON
shapes, flagship-gif interactive recording, mypy-extractor maintainer call). Nothing
safe and valuable to do; per idle-is-success, no work was manufactured.

**Stale-clone note (handled cleanly this time):** the session again started with a
detached HEAD at the true remote tip `02973c4` while the cached `origin/main` ref
pointed at the old disjoint `211a31d`. Per the prior run's lesson I fetched first;
`git fetch` reconciled `origin/main` → `02973c4` (forced update, no real divergence)
before any analysis. Re-attached `main` and recorded this entry. No backup branches,
no issues opened.

---

## AUDIT (2026-06-19, eighth)

Reviewer: independent checker agent. Previous AUDIT marker: `a743f64` (seventh audit).
Reviewed 4 commits from `f9d0e88` through `0d18884`.

### Test and lint gate

`uv run pytest`: 229 passed, 1 skipped (env-gated e2e — correct). Up from 224 in the seventh audit.
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `f9d0e88` | fix: guard the post-revert untracked-file listing against OSError |
| `823f826` | feat: add 'looptight next' — in-session task driver (no agent spawn) |
| `00a3bb1` | docs: document 'looptight next' and the session-token in-session loop |
| `0d18884` | docs: log improver run (no changes; escalations recorded) |

### Verdict: clean; no concerns

**`f9d0e88` — resolves seventh-audit concern, correct:**
Directly addresses the concern flagged in the seventh audit: the informational `git
ls-files` call added by `fe626a5` lacked the `try/except OSError` that wrapped the
preceding `git checkout`. The fix wraps the call and falls back to `leftovers = []`
on failure, ensuring a revert that already succeeded can never be crashed by the
follow-up listing. One targeted test covers the exact scenario. Resolution is clean
and precisely scoped.

**`823f826` — new `looptight next` command, in scope and minimal:**
Adds a thin in-session task driver: `looptight next` prints the single next task
(top grounded `propose` candidate, or a fresh audit goal when the queue is empty)
for the current agent session to execute on its own tokens, bypassing `improve`'s
`claude -p` / `codex exec` agent spawn. Core logic is 7 lines (`next_task` in
`improve.py`), reusing `_grounded_goal` and `_audit_goal` which already existed.
`cmd_next` is 6 effective lines. No new abstractions, no new dependencies.
File sizes all within the 200–400 line guideline (`commands.py` at 384,
`improve.py` at 261). Four new offline tests cover the grounded-task path, the
audit fallback, and the CLI contract. The feature fills a real gap: the Stop hook
covers single-iteration continuation; `improve` spawns agents; `next` covers
in-session multi-task iteration explicitly. The `_audit_goal(1, [])` default is
reasonable — produces a generic audit instruction, the right fallback when the
propose queue is empty.

**`00a3bb1` — README docs, accurate:**
Adds a 20-line section describing `next` and the session-tokens-vs-API-credits
distinction. Accurately describes the `next → implement → verify → commit` flow.
In scope and factually correct.

**`0d18884` — idle improver run log, correct:**
Records no code changes; cites `224 passed` (accurate for that point in
history). All five propose candidates correctly identified as non-actionable
offline. Consistent with prior idle-run entries.

No prior audit concerns remain open.

---

## IMPROVER run (2026-06-19)

No changes: nothing safe and valuable to do. On entry `uv run pytest -q`
(224 passed, 1 skipped) and `uv run ruff check` were both clean; no real
TODO/FIXME markers in `src/`. All five `looptight propose` candidates were
no-ops or unverifiable offline:

- **tests/e2e_test.py:23, :37 (un-skip skipped tests)** — intentionally opt-in.
  The module gates on `LOOPTIGHT_E2E` and skips when no agent is on PATH; it
  needs a real coding agent, live auth, and costs money, so it is correctly
  excluded from the offline default run. Not a defect; left as-is.
- **Confirm Codex `/goal` headless drive (STATUS Next #1)** — requires observing
  the real Codex CLI's interactive behaviour, unavailable offline. Skipped;
  do not guess `supports_native_loop` / `drive_native_loop`.
- **Parse cost from `codex exec --json` / `opencode run -f json` (Next #2)** —
  depends on the exact JSON shape those CLIs emit, unobservable here. Skipped
  rather than invent a parser against an assumed format.
- **Record the flagship gif (Next #3)** — needs real agents running end-to-end;
  not an offline code task. Skipped.

---

## AUDIT (2026-06-19, seventh)

Reviewer: independent checker agent. Previous AUDIT marker: `7a2daee` (sixth audit).
Reviewed 23 commits from `ae0c6bb` through `c10065e`.

### Test and lint gate

`uv run pytest`: 224 passed, 1 skipped (env-gated e2e — correct). Up from 204 in the sixth audit.
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `ae0c6bb` | docs: reviewer audit entry 2026-06-19 (sixth) |
| `6db8c51` | fix: stop the improve loop after consecutive idle tasks |
| `c4f5ec4` | fix: collapse multi-line reflections into a single lesson bullet |
| `3a92851` | fix: don't read a Make 'test' assignment as a test target |
| `b13a478` | test: pin the improve idle-guard disable escape hatch |
| `4b1e446` | fix: don't show $0.00 cost for agents that don't report it |
| `b9361d9` | fix: honest cost in the improve summary line too |
| `601b74e` | fix: warn when run --budget can't be enforced |
| `a421c9a` | feat: show the resolved config path in doctor |
| `fe626a5` | fix: tell the user when revert leaves untracked files behind |
| `f64532d` | test: cover render_rich, the user-facing run summary |
| `0726454` | fix: exit cleanly on Ctrl-C instead of dumping a traceback |
| `37f9f88` | fix: verify oracle tolerates non-UTF-8 command output |
| `3484edf` | fix: agent runner tolerates non-UTF-8 CLI output |
| `f199506` | fix: init refuses to clobber an existing config |
| `fb4041e` | fix: lessons reads the configured agent's memory file |
| `13990d1` | test: pin that run exits 1 when verify never passes |
| `efb6ac4` | fix: run banner shows honest budget for non-cost-reporting agents |
| `904f15e` | feat: add mypy type-error extractor to propose |
| `8566c1e` | docs: reflect that the mypy type extractor is implemented |
| `a85cb73` | test: pin from_types graceful degradation without mypy |
| `37eb255` | docs: escalate mypy-extractor gate decision to maintainer |
| `c10065e` | revert: drop the mypy from_types extractor (maintainer decision) |

### Verdict: clean; one minor style inconsistency flagged (no revert)

**`6db8c51` (idle guard) — correct and necessary:**
`run_improve` had no stopping condition for unattended runs with no session
budget (the only mode for codex/opencode, which report $0 USD so the budget
can never trip). The audit path would spin forever once the repo ran dry.
The fix adds a `consecutive_idle` counter reset on every commit, incremented
on both "no changes" and "failed verify" outcomes, with a `max_idle_tasks=3`
default and a `<= 0` escape hatch. Logic is sound. `NO_PROGRESS` is correctly
wired to exit code 0 in `cmd_improve`. Four new tests cover the trigger,
a mid-streak reset, the escape hatch, and the unverified path.

**`c4f5ec4` (reflection collapse) — real data-loss bug, correct fix:**
`reflect_on_failure` preserved internal newlines in lesson text. The lessons
store is line-based (`parse_lessons` matches one bullet per line), so any
multi-line lesson lost every line after the first on round-trip. `" ".join(raw.strip().strip("-•* ").split())` correctly flattens to a single line. One edge
case (interior `•` characters become inline text) is acceptable behaviour.

**`3a92851` (Makefile regex) — correct:**
Old code used `line.startswith("test:")`, which matched variable assignments
(`test:=pytest`, `test::=`). New regex `r"test\s*:(?!:?=)"` uses a negative
lookahead that correctly rejects both `test:=` (`:?` matches nothing, `=`
matches) and `test::=` (`:?` matches `:`, `=` matches). Real targets
(`test:`, `test: prereqs`) still match. Logic verified.

**Cost-honesty cluster (`4b1e446`, `b9361d9`, `601b74e`, `efb6ac4`) — complete and correct:**
All four coordinate to give non-cost-reporting agents (codex/opencode) honest
UX: no misleading `$0.00` in the iteration line, summary footer, improve
summary, or startup banner; `--budget` warns it cannot be enforced. The new
`reports_cost_usd: bool = True` field on the frozen `RunResult` dataclass is
minimal and correctly defaulted. `render_rich` pragma dropped after gaining
coverage in `f64532d`.

**Robustness cluster (`37f9f88`, `3484edf`) — critical path hardening:**
Both the verify oracle and the adapter runner decoded output with the strict
codec; an agent emitting invalid UTF-8 raised an uncaught `UnicodeDecodeError`
not caught by the existing `OSError`/`TimeoutExpired` handlers. Fixed with
`errors="replace"` in both subprocess calls. Minimal, correct, and load-bearing
(verify is the contract).

**`f199506` (init clobber) — real data-loss fix:**
Re-running `init` silently overwrote a user's customized config. Now refuses
when the file exists. Correct.

**`fb4041e` (lessons agent resolution) — real bug fix:**
`cmd_lessons` ignored `config.agent`, so a project configured for codex would
read an empty `CLAUDE.md`. Resolution order now matches `run`/`improve`:
CLI flag > config > detect.

**`a421c9a` (doctor config path) — small, useful, in scope:**
Shows the resolved `.looptight.toml` path (or "none (using defaults)") so a
user can debug a silently-not-applied config. One targeted test.

**`0726454` (Ctrl-C) — correct:**
`KeyboardInterrupt` now caught at the top level; returns exit 130
(conventional SIGINT code). The improve loop's own `KeyboardInterrupt` catch
(which does rollback first) is unaffected.

**`fe626a5` (revert untracked warning) — correct in substance:**
After reverting tracked files, the command now runs `git ls-files --others
--exclude-standard` and reports any untracked leftovers. The main `git
checkout` call is wrapped in `try/except OSError`; the follow-up
`ls-files` call is not. In practice this cannot fail (git was proven
available seconds earlier), but the inconsistency is a style concern — noted
below.

**mypy arc (`904f15e` → `8566c1e` → `a85cb73` → `37eb255` → `c10065e`) — correctly handled:**
The extractor was added, escalated by the sixth audit for a maintainer
decision (mypy is not part of the quality contract), and reverted by the
maintainer. Final state is clean: `from_types` and `_mypy_candidates` are
absent; the `types` source weight is re-reserved for a future extractor;
the escalation is recorded as resolved in REVIEW-QUEUE. No test or code
residue remains.

**20 new tests — targeted and offline:** All cover real gaps (render_rich,
idle guard paths, exit-code regression, etc.). No padding. All sub-second.

### Minor concern flagged (no revert)

**`fe626a5`: `git ls-files` call in `cmd_revert` lacks `try/except OSError`.**
The informational `git ls-files` call added after the main revert runs without
the `OSError` guard that wraps the `git checkout` call above it. If git were
removed from PATH between the two calls (unrealistic, but theoretically possible
in a container), the exception would propagate uncaught. The existing guard on
the earlier call makes the inconsistency visible. Suggest adding a bare
`except OSError` that sets `leftovers = []` around the second `subprocess.run`.
Flag only — no revert; the fix is purely defensive.

---

## ESCALATION (2026-06-19) — mypy extractor: gate-or-not decision (maintainer call)

**RESOLVED (2026-06-19): maintainer chose to revert `from_types`.** mypy is not
part of looptight's quality contract, so the extractor only produced noise here
(the `config.py:48` false-positive + test import-not-found). Reverted in a
follow-up commit; `_SOURCE_WEIGHT["types"]` is reserved again for a future
extractor if mypy is ever adopted as a real gate. Original escalation below.

The new `from_types` mypy extractor (commits `904f15e`/`8566c1e`/`a85cb73`) now
surfaces type findings via `propose`. First run encountering its output:

- `mypy src/looptight` → **4 errors, all on `config.py:48`**, the
  `replace(self, **clean)` idiom where `clean: dict[str, object]`. This is a
  well-known mypy false-positive (it can't see through `**dict` to the dataclass
  field types); the code is correct at runtime.
- `mypy` over `tests/` additionally reports 6 `import-not-found` findings
  (pytest, rich.console) — pure noise from missing stubs in the run env, not
  defects.

**Not auto-fixed, deferred to maintainer.** Reasons: mypy is not part of the
quality contract (not in dev deps, not in CI, no config) and the codebase has
zero `# type: ignore` comments by design. "Fixing" `config.py:48` would mean
introducing the first `type: ignore`/cast purely to satisfy a non-gating tool —
unenforced (would silently regress) and out of contract — and would not make
`mypy` clean overall (the test import-not-found findings remain). Whether to
adopt mypy as a real gate (deps + CI + `ignore_missing_imports`, and scope the
extractor to `src` so it stops surfacing test-import noise) is a project-
direction decision, not something to guess autonomously.


## AUDIT (2026-06-19, sixth)

Reviewer: independent checker agent. Previous AUDIT marker: `966f4f6` (fifth audit).
Reviewed 19 commits from `bd1ef12` through `7a2daee`.

### Test and lint gate

`uv run pytest`: 204 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.** (Test count grew from 175 → 204; 29 new tests, all offline.)

### Commits reviewed

| Hash | Subject |
|------|---------|
| `bd1ef12` | docs: reviewer audit entry 2026-06-19 (fifth) |
| `3a45a5a` | docs: record idle improve run 2026-06-19 (no actionable work) |
| `71ef76f` | chore: Record the flagship gif (marks item ~~struck through~~ as deferred) |
| `fc60862` | fix: keep idle improve audits read-only |
| `fb37a8f` | chore: autonomous repository improvement 2 |
| `040d17f` | chore: autonomous repository improvement 3 |
| `9a1552d` | chore: autonomous repository improvement 4 |
| `f6c4a53` | chore: autonomous repository improvement 5 |
| `b9ba7b8` | chore: autonomous repository improvement 6 |
| `69770c1` | chore: autonomous repository improvement 7 |
| `b9c566e` | chore: autonomous repository improvement 8 |
| `93cf248` | chore: autonomous repository improvement 9 |
| `d25e682` | chore: autonomous repository improvement 10 |
| `f1328ad` | chore: autonomous repository improvement 11 |
| `4244505` | chore: autonomous repository improvement 12 |
| `25a7938` | chore: autonomous repository improvement 13 |
| `4bf06f5` | chore: autonomous repository improvement 14 |
| `8146cff` | chore: autonomous repository improvement 15 |
| `7a2daee` | chore: autonomous repository improvement 16 |

### Verdict: clean; no concerns

**Docs commits (`bd1ef12`, `3a45a5a`, `71ef76f`) — accurate:**
`bd1ef12` is the fifth audit entry. `3a45a5a` is an idle improve run (no code
changes, all 5 propose candidates non-actionable offline). `71ef76f` strikes
through the flagship-gif STATUS.md item and links to REVIEW-QUEUE's deferred
section — accurate bookkeeping; commit message is truncated but harmless.

**`fc60862` — prompt hardening, correct:**
Strengthened the `_audit_goal` prompt to explicitly forbid editing
REVIEW-QUEUE.md or STATUS.md just to log "no work found", and to require
leaving the working tree unchanged when no evidence-backed improvement exists.
Two new tests assert the relevant phrases are present in the prompt text.

**Improvements 2–16 — all correctness/robustness fixes, each with targeted tests:**

- **fb37a8f** (`_boolean` helper): TOML boolean fields (`reflect`, `native`, `hook`)
  previously accepted `"false"` silently as `True` (`bool("false") == True`). Now
  rejects non-bool values with a clear error.
- **040d17f** (`run_command` helper): extracted identical `subprocess.run` boilerplate
  from all three adapters into a shared `run_command()` in `base.py` that also
  normalizes `OSError` to a non-zero result. Real DRY improvement + correctness fix.
- **9a1552d** (`_stop_hooks` helper): `hooks.Stop` being a non-list (e.g. a dict)
  would silently corrupt state via `list(dict)` (iterates keys). Now rejects with
  a clear error. File is left unchanged on error (test verifies).
- **f6c4a53** (generic exception rollback): unexpected exceptions from the task runner
  now trigger rollback before returning `PROVIDER_STOP`, rather than propagating
  and leaving the working tree dirty.
- **b9ba7b8** (`_non_negative_int`): `--limit -1` for `propose` rejected at the
  CLI layer (exit code 2) rather than silently passing a negative limit.
- **69770c1** (timeout partial output): `subprocess.TimeoutExpired` carries
  `.stdout`/`.stderr` captured before the kill; this is now prepended to the
  "timed out" message and the SCORE parsed from it, giving the next iteration
  useful context. Real improvement to the verify oracle under timeout.
- **b9c566e** (`_optional_string`): `verify` and `agent` config fields now reject
  non-string values (e.g. `42`) at load time rather than silently propagating the
  wrong type.
- **93cf248** (injection guard in reflect): if a model's reflection output contains
  `BLOCK_START` or `BLOCK_END` (lesson store delimiters), the lesson is discarded
  rather than written, preventing delimiter injection that would corrupt CLAUDE.md.
  Correct and minimal security fix.
- **d25e682** (checkpoint git OSError): `checkpoint._git()` now normalises `OSError`
  (e.g. git not installed) to a non-zero `CompletedProcess`, consistent with the
  rest of the codebase.
- **f1328ad** (non-dict `scripts` in package.json): `{"scripts": null}` or
  `{"scripts": [...]}` would previously crash `detect_verify` with `AttributeError`.
  Now falls through gracefully.
- **4244505** (`_is_ours` non-list guard): hook entries with `"hooks": null` would
  cause `for h in None` to crash. Now returns `False` for malformed entries,
  preserving them and still installing the new entry.
- **25a7938** (`_positive_int` / `_positive_integer`): `--max-iterations 0` (CLI)
  and `max_iterations = 0` (config) are now rejected. The config helper correctly
  checks `isinstance(value, bool)` before `isinstance(value, int)` to exclude TOML
  booleans.
- **4bf06f5** (hook fail-open on `write_count`): `OSError` saving iteration state
  now returns `None, 0` (don't block the session) instead of propagating. Rationale
  documented in the diff: without durable state the hook would deadlock forever.
- **8146cff** (rollback before GIT_ERROR on status failure): `git status` failing
  after a successful task was returning `GIT_ERROR` without rolling back changes.
  Test verifies working tree is clean afterward.
- **7a2daee** (revert OSError): `cmd_revert`'s direct `subprocess.run` call now
  catches `OSError` and returns exit code 1 with a clear message, consistent with
  the rest of the codebase.

All 29 new tests are targeted, offline, and sub-second. No new runtime dependencies.
No speculative abstractions. No test padding. The `chore:` prefix convention on
improvement commits was noted in prior audits and left as-is; no new concern there.

---

## Run Summary (2026-06-19, idle run)

No changes: nothing safe and valuable to do. Verified main is green
(`uv run pytest`: 175 passed, 1 skipped env-gated e2e; `uv run ruff check`:
clean). HEAD at `bd1ef12`.

`uv run looptight propose` surfaced 5 candidates, none actionable offline:

- **skipped-test ×2 (`tests/e2e_test.py:23`, `:37`)** — the intentional opt-in
  real-agent eval. Requires an installed agent on PATH, live auth, and real
  spend; deliberately excluded from offline CI. The skip is correct; un-skipping
  would violate the never-weaken-tests floor and can't be verified here.
- **status-next: confirm Codex `/goal` headless** — needs observation of the real
  `codex` CLI. Already escalated; still deferred.
- **status-next: parse cost from `codex exec --json` / `opencode run -f json`** —
  needs the real CLIs' JSON output formats, unobservable here. Still deferred.
- **status-next: record the flagship gif** — interactive recording across three
  real agents, not an autonomous code change. Still deferred.

An empty run is a good run.

---

## AUDIT (2026-06-19)

Reviewer: independent checker agent. Previous AUDIT marker: `d16f2a9`.
Reviewed 2 commits from `ec2adfb` through `41e0d93`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `ec2adfb` | docs: reviewer audit entry 2026-06-19 |
| `41e0d93` | docs: record idle improve run 2026-06-19 (no actionable work) |

### Verdict: clean; recurring minor documentation inaccuracy noted (no action)

**`ec2adfb` — docs only, accurate:**
Appends the prior audit entry to REVIEW-QUEUE.md. Records `fe5b637` and
`d16f2a9` as docs-only commits, both clean. Test count (175/1) and ruff
status match current ground truth. Self-consistent.

**`41e0d93` — docs only, correct in substance:**
Another idle improve run — no code changes. `propose` surfaced only the
flagship-gif task (already escalated, correctly skipped). The run correctly
defers to "escalate-don't-guess".

**Recurring: improve-run summaries cite `113 passed` when actual count is
`175`.**
This has appeared in several idle-run summaries now. The discrepancy
reflects the session baseline from a prior point in time before later test
growth. The actual ground truth (175/1 green) is always confirmed by the
audit; prior audits have accepted this explanation. However, the pattern
is now well-established: the improve agent's internal pytest baseline is
not refreshed between sessions, meaning its summaries do not reflect the
current test count. This is docs inaccuracy only — no code is affected and
no regression is hidden (the gate command always runs fresh). Flag only;
no revert.

No code was modified in either commit. No new concerns beyond the
recurring docs inaccuracy noted above.

---

## AUDIT (2026-06-19)

Reviewer: independent checker agent. Previous AUDIT marker: `ee68c74`.
Reviewed 2 commits from `fe5b637` through `d16f2a9`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `fe5b637` | docs: reviewer audit entry 2026-06-18 (third) |
| `d16f2a9` | docs: record idle improve run 2026-06-19 (no actionable work) |

### Verdict: clean; no concerns

**`fe5b637` — docs only, accurate:**
Appends the previous audit's findings to REVIEW-QUEUE.md. Records that
`78fe32e` (cli/commands refactor) and `ee68c74` (idle-run docs) were reviewed
and found clean. The entry is self-consistent: test count matches (175/1), both
prior concerns are correctly marked resolved, no revert was issued.

**`d16f2a9` — docs only, accurate:**
Records the 2026-06-19 idle improve run. No code changes; `propose` surfaced
only the flagship-gif task (already escalated, correctly skipped). The entry
is consistent with prior idle-run summaries. Test count (113 passed) cited in
that entry appears to be from the session's baseline before later test growth;
the current green state (175 passed) is the ground truth and confirms no
regressions.

No code was modified. Test count and ruff status are unchanged from the prior
audit. No new concerns to flag.

---

## AUDIT (2026-06-18)

Reviewer: independent checker agent. Previous AUDIT marker: `6d15e90`.
Reviewed 2 commits from `78fe32e` through `ee68c74`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `78fe32e` | refactor: extract CLI command handlers into commands.py |
| `ee68c74` | docs: record idle improve run (no actionable work) |

### Verdict: clean; no concerns (previous concerns resolved)

**`78fe32e` — pure mechanical extraction, correct:**
This directly resolves audit concern #1 from `6d15e90`: `cli.py` had grown to
464 lines (above the 200–400 guideline). The `cmd_*` handler functions moved
verbatim into `src/looptight/commands.py` (321 lines); `cli.py` is now 163
lines — a thin parser + dispatcher. No logic was changed. All `monkeypatch`
targets in `tests/test_cli.py` were correctly updated from
`looptight.cli.<name>` to `looptight.commands.<name>`. Tests stayed at 175
passed, 1 skipped. The commit message accurately describes what moved and why.

Both flagged concerns from the prior audit are now resolved:
- **Concern #1 (cli.py size):** resolved by `78fe32e`.
- **Concern #2 (chore: prefix on audit commits):** reviewed and left as-is by
  the idle-run summary (`ee68c74`); rationale accepted — a derived prefix risks
  being more misleading than a predictable uniform `chore:`. Closed.

**`ee68c74` — docs only, accurate:**
Records that the idle improve run found nothing actionable; correctly notes both
prior audit concerns as resolved; does not introduce any code changes.

No new concerns to flag. The escalated items (Codex `/goal`, cost parsing,
flagship gif) remain unchanged and correctly deferred.

---

## Run Summary (2026-06-18, idle run)

No changes: nothing safe and valuable to do. Verified main is green
(`uv run pytest -q`: 175 passed, 1 skipped env-gated e2e; `uv run ruff check`:
clean).

- The single `propose` candidate is the flagship-gif task (STATUS.md Next #3),
  a deferred non-goal needing interactive recording across three real agents —
  not an autonomous code change. Unchanged from prior runs.
- Audit concern #1 (cli.py at 464 lines) is **resolved**: `78fe32e` extracted
  the command handlers into `commands.py`; cli.py is now 163 lines and every
  source file is within the 200–400 guideline.
- Audit concern #2 (audit-path commits all use `chore:`) was reviewed and left
  as-is: deliberately flagged "no revert, cosmetic." Source does not reliably
  map to a conventional-commit type (a `status-next` item can be docs, feat, or
  fix), so a derived prefix would risk being as misleading as the honest,
  predictable uniform `chore:`. Not a clearly-valuable change.

An empty run is a good run.

---

## AUDIT (2026-06-18)

Reviewer: independent checker agent. Previous AUDIT marker: `296d40e`.
Reviewed all 24 commits from `0c2462d` through `0ebe480`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `0c2462d` | fix: document budget as a spend threshold |
| `80c0388` | ci: enforce ruff on every change |
| `be0f453` | docs: define continuous improve mode |
| `26e8eec` | docs: plan continuous improve command |
| `ce220d1` | docs: clarify tracked-file checkpoint scope |
| `9990bbd` | fix: propagate coding agent failures |
| `75d8bdd` | feat: add continuous improvement engine |
| `73a96a0` | feat: add continuous improve command |
| `46953ad` | chore: Confirm whether Codex /goal can be driven headlessly |
| `f808d28` | fix: skip resolved status proposals |
| `13cf1f5` | chore: Decide whether to add token-to-USD pricing |
| `abe78fd` | chore: Record the flagship gif (README table fix) |
| `042dfc6` | chore: autonomous repository improvement 3 (`_is_ours` exact-match fix) |
| `63a0294` | chore: autonomous repository improvement 4 (TOML string escaping) |
| `f647492` | chore: autonomous repository improvement 5 (hook non-string cwd guard) |
| `403573c` | fix: join wrapped continuation lines in STATUS Next parser |
| `9bd8f06` | fix: fail cleanly on a malformed .looptight.toml |
| `968ea7e` | docs: record idle improve run (no actionable work) |
| `d857aaa` | fix: reach the hooks-not-an-object guard in settings surgery |
| `584c6ec` | fix: keep the Stop hook dormant on a malformed config |
| `1f34bad` | fix: harden claude JSON parsing against unexpected output shapes |
| `69b5f38` | fix: truncate autonomous commit subjects on a word boundary |
| `0116665` | fix: parse verify SCORE from full output before truncating |
| `0ebe480` | docs: record robustness-hardening session in REVIEW-QUEUE |

### Verdict: clean; two minor style concerns flagged (no revert)

**Correctness fixes — all legitimate and well-tested:**
- `9990bbd` (propagate agent failures): real gap — a provider error was silently
  treated as a failed iteration, letting the loop continue or misreport the cause.
  `StopReason.ERROR` now propagates correctly from both supply and delegate paths.
  `reports_cost_usd` flag correctly scopes session-budget tracking to Claude only.
- `0c2462d` (budget documentation): `budget_usd` was documented as a hard ceiling
  but is a post-iteration threshold; docs now match reality.
- `f808d28` (struck-through status items): `~~resolved~~` items in STATUS.md Next
  no longer surface as candidates.
- `042dfc6` (`_is_ours` exact match): changed from substring containment to exact
  equality for hook command identity — prevents false matches on user commands that
  merely contain the hook command string.
- `63a0294` (TOML string escaping): `render_config` now uses `json.dumps()` to
  safely encode the verify command, fixing silent data loss for commands with
  quotes, backslashes, or newlines.
- `f647492` (hook non-string cwd): hardens against a non-string `cwd` in the hook
  event JSON crashing `Path()`.
- `403573c` (wrapped continuation lines): STATUS.md items that wrap onto indented
  continuation lines are fully captured. Logic is sound.
- `9bd8f06` (malformed config): `ConfigError` is now raised at the boundary,
  giving a clear message instead of a raw traceback.
- `d857aaa` (settings type guard): type check moved before the `dict()` conversion
  that would crash on a non-dict hooks value — dead code path is now reachable.
- `584c6ec` (hook dormant on broken config): `ConfigError` caught in `_config_for`;
  hook correctly falls back to the un-armed default.
- `1f34bad` (claude JSON parsing): non-object JSON blobs and non-numeric cost
  values are now degraded safely rather than crashing an iteration.
- `69b5f38` (word boundary truncation): commit subjects no longer end mid-word.
- `0116665` (SCORE parsing): score is parsed from full combined output before
  truncation, so a SCORE line in the middle of verbose output is not silently lost.

**New feature (`improve.py` + CLI) — correct and in-scope:**
`75d8bdd` + `73a96a0` add the continuous improvement engine (`looptight improve
--push`) described in CLAUDE.md. The design is sound: verify-gated, injected
collaborators, frozen dataclasses, 200+ lines of offline tests covering rollback,
budget stop, provider failure, keyboard interrupt, and the grounded→audit
transition. The loop correctly guarantees a clean working tree before each task
and rolls back on failure (`git reset --mixed HEAD`, `checkout HEAD -- .`,
`git clean -fd`). `verify` stays the gate.

**Architecture docs — accurate.** `46953ad` and `13cf1f5` record confirmed
decisions (Codex `/goal` is self-graded, not a verify-gated loop; Codex USD
cost estimation deferred) correctly and mark the STATUS.md items resolved.

### Concerns flagged for next improver run

**`cli.py` at 464 lines (above the 200-400 line guideline).**
The file grew to accommodate 10 subcommands. The logic lives in the right modules;
the CLI only wires them together. Nevertheless, at 464 lines it is meaningfully
above the stated guideline. A straightforward split would extract the individual
`cmd_*` handler functions into `src/looptight/_commands.py` (or a `commands/`
subpackage), leaving `cli.py` as the thin parser and dispatcher. This would bring
both files within range without touching any logic. Flag only — no revert.

**Chore commits from the audit path all use `chore:` prefix regardless of content.**
`042dfc6` (`_is_ours` correctness fix) and `f647492` (hook non-string cwd guard)
are real bug fixes but were committed as `chore:` because they came from the
improve loop's audit path rather than a grounded `propose` candidate. The
`_commit_subject` function in `improve.py` always prefixes with `chore:` for
audit tasks. Consider deriving the conventional-commit prefix from the change
type (fix vs. docs vs. refactor) or from a `Candidate.source` field on audit
candidates. Flag only — no revert; fixes are correct, history is slightly
misleading.

---

## Run Summary (2026-06-18, robustness-hardening session)

Interactive autonomous loop, engineer-driven. Seven substantive correctness/
robustness fixes landed, each TDD'd (red→green) and gated on `uv run pytest -q`
+ `uv run ruff check` clean before push. Focus: harden the boundaries against
untrusted external input (agent-CLI output, config files, settings files) and
protect the load-bearing `verify` contract the audit flagged below.

### Landed

| Hash | Description |
|------|-------------|
| `403573c` | fix: join wrapped continuation lines in STATUS `Next` parser (was truncated mid-sentence) |
| `9bd8f06` | fix: `load_config` raises a clear `ConfigError` (+ CLI catch) instead of a raw traceback on malformed `.looptight.toml` |
| `d857aaa` | fix: reach the hooks-not-an-object guard in `settings.py` (dead code: `dict()` crashed first); same guard added to `uninstall` |
| `584c6ec` | fix: keep the Stop hook dormant on a malformed config (was crashing the subprocess, breaking `run_hook`'s documented contract) |
| `1f34bad` | fix: harden claude JSON parsing against non-object blobs / non-numeric cost (untrusted CLI output) |
| `69b5f38` | fix: truncate autonomous commit subjects on a word boundary (were cut mid-word, e.g. `...then a seco`) |
| `0116665` | fix: parse verify `SCORE:` from full output before truncating — a score in the truncated-away middle was silently lost (score-gated loops) |

### On the audit's governance concern

The AUDIT below flags that CLAUDE.md removed the human-in-the-loop checkpoint,
so `verify` is now solely load-bearing. `0116665` directly hardens that path:
the oracle no longer drops a `SCORE:` signal on verbose output. The merge gate
itself (exit-code pass/fail) was already correct and is unchanged.

### Not done

The remaining `propose` / escalated items (Codex `/goal` headless drivability,
Codex/opencode USD cost parsing, flagship gif) are all blocked on observing real
external-CLI output or interactive recording — unchanged from prior runs,
escalate-don't-guess.

---

## Run Summary (2026-06-18, idle run)

No changes: nothing safe and valuable to do. Verified main is green
(`uv run pytest -q`: 169 passed, 1 skipped; `uv run ruff check`: clean). The
only remaining `propose` candidate is the flagship-gif task, already recorded
below as a deferred non-goal (needs an interactive recording environment with
three real agents — not an autonomous code change). The propose-noise filtering
for opt-in/conditional skips is already landed (`4a4860e`, `e78f2ca`), so no
further work there. An empty run is a good run.

---

## AUDIT (2026-06-18)

Reviewer: independent checker agent. No prior AUDIT marker found; reviewed the
last 20 commits (full history since project inception of the queue).

### Commits reviewed

| Hash | Subject |
|------|---------|
| `9729340` | docs: make dogfood loop fully autonomous |
| `b8e8cbc` | docs: define dogfood improvement loop |
| `ecd8bcd` | docs: record observed codex json usage output |
| `d7182d1` | docs: append fourth-run summary to REVIEW-QUEUE |
| `e78f2ca` | fix: stop propose flagging capability-guarded skips as fix-me |
| `3ef80d2` | docs: append third-run summary |
| `4a4860e` | fix: stop propose from flagging opt-in eval tests as fix-me skips |
| `2fcf6b0` | docs: append run summary (second run) |
| `838cabe` | test: cover on_iteration in delegate path + cmd_run with no verify |
| `36ce16c` | test: cover codex/opencode reflect() success/non-zero-exit paths |
| `1a2d4aa` | test: cover malformed package.json falling through in detect_verify |
| `8e56509` | test: verify from_todos ignores TODO inside string literals |
| `3aaab09` | test: add coverage for cmd_verify, cmd_propose --json, cmd_lessons |
| `75cd572` | fix: render_rich now shows diffstat; test plain render diffstat branch |
| `1230b53` | build: add pytest to dev dependency group |
| `29830fd` | test: add direct unit tests for reflect_on_failure (9 tests) |
| `d59bfea` | docs: add REVIEW-QUEUE.md with run summary and escalations |
| `65f31f3` | test: cover pytest.ini and tox.ini detection rules |
| `36ac826` | test: add missing detect_verify coverage for Cargo.toml |
| `604a480` | fix: from_lint output-format bug + add tests |

Also reviewed new commits on origin/main since audit started:
| `9248496` | docs: plan checkpoint failure hardening |
| `a6f145b` | fix: reject failed git checkpoints |

### Test and lint gate

`uv run pytest`: 139 passed, 1 skipped (the env-gated e2e test — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Verdict: mostly clean; one concern flagged (no revert)

**Substantive fixes — correct:**
- `604a480` (`from_lint` ruff flag): real bug, ruff `--quiet` changed output
  format; fix is minimal and targeted.
- `75cd572` (`render_rich` diffstat): real omission — rich summary silently
  dropped the "what changed" block. Fix is three lines, correct.
- `4a4860e` / `e78f2ca` (propose skip-filtering): two incremental fixes to
  `from_skipped_tests`. Logic is sound; `_inside_conditional` walks back to
  nearest enclosing block and checks `if|elif` only — edge cases considered
  and handled correctly. Both have matching offline tests.
- `a6f145b` (checkpoint failure): reject a failed git stash create by
  checking the return code; prevents silently proceeding with a broken
  snapshot. Real correctness fix; tests added.

**Tests — legitimate coverage, not padding:**
All test-only commits cover genuine gaps: untested CLI commands, error paths
(malformed JSON, non-zero reflect exits), and the delegate-path `on_iteration`
callback. `reflect_on_failure` (29830fd) was tested only indirectly through the
loop; direct tests on a critical path are worthwhile. File sizes remain within
the 200–400 line guideline.

**Build (`1230b53`):** Adding pytest to `[dependency-groups]` alongside
`[project.optional-dependencies]` is the modern uv-native approach, not churn.
Lock file changes are uv-generated `upload-time` metadata, not new dependencies.

**Docs — accurate, no code risk.**

### Concern flagged for next improver run

**`9729340` — governance shift in CLAUDE.md (flag only, do not revert).**
This commit changed the stated operating model from
*"a human approves what runs / substantive work goes on a branch and is
reviewed before main"* to *"No human participates in the task cycle / agent
selects, reviews diff, commits, and pushes directly to main."* The code
itself is unchanged, `verify` remains the merge gate, and the tests all pass.
However, the human-review checkpoint has been explicitly removed from the
documented operating discipline, which raises the stakes if `verify` misses a
correctness defect. The concern is not in scope for revert (it is a process
decision, not a code regression), but the next improver run should note that
the human-in-the-loop safety check now relies entirely on the checker agent
(this role) rather than a human reviewer. The architectural principle "verify
is the contract" must be treated as load-bearing.

---

## Escalated (2026-06-18)

### Cannot observe external CLI output formats

**Codex `/goal` headless drivability**
Cannot confirm whether `codex /goal` can be driven headlessly (`codex exec /goal …`).
If it can, `CodexAdapter.supports_native_loop` should be set to `True` and
`drive_native_loop` implemented. Blocked on running a real Codex CLI session.
Source: `docs/STATUS.md` → Next #1.

**Codex/opencode cost parsing**
`codex exec --json` was observed on 2026-06-18: the `turn.completed` event
includes `usage.input_tokens`, `usage.cached_input_tokens`,
`usage.output_tokens`, and `usage.reasoning_output_tokens`, but no USD cost.
Implementing a Codex `cost_usd` estimate now requires an explicit model/pricing
mapping decision, not just parsing. `opencode run -f json` remains unobserved
because `opencode` is not installed in this environment.
Source: `docs/STATUS.md` → Next #2.

**e2e test un-skip**
`tests/e2e_test.py` is intentionally gated behind `LOOPTIGHT_E2E=1` and requires
a real coding agent + auth. Un-skipping it in CI requires setting up agent auth
in the CI environment; not safe to do autonomously.
Source: `propose` output → skipped-test items.
_Update (2026-06-18, third run):_ the **propose-noise** half of this is now
resolved in code — `from_skipped_tests` no longer surfaces env-gated opt-in
evals (commit `4a4860e`). Actually *running* the e2e test in CI still needs
agent auth and remains escalated.

### Deferred non-goal

**Flagship gif**
Recording a gif of the same command across agents (docs/STATUS.md Next #3)
requires an interactive recording environment and is not an autonomous code
change.

---

## Run Summary (2026-06-18, third run)

Autonomous improvement loop. One substantive fix landed; remaining `propose`
items are all already-escalated (external-CLI / gif). Resisted padding the
already-dense suite (134 tests / ~2150 LOC) — correctness over quantity.

### Landed

| Hash | Description |
|------|-------------|
| `4a4860e` | fix: stop `propose` from flagging opt-in eval tests as fix-me skips |

`from_skipped_tests` was surfacing `tests/e2e_test.py` (the env-gated
`LOOPTIGHT_E2E` opt-in eval) as an "un-skip / fix" candidate on every run —
noise that ranked above the real status-next items and buried signal. The fix
recognises an env-var opt-in gate (`skipif(not os.environ.get(...))`), handles
conditions that wrap onto following lines, and treats a module wholesale gated
by such a `pytestmark` (incl. inner `pytest.skip` guards) as intentional. Three
new offline tests; `propose` output dropped from 5 candidates (2 noise) to 3
genuine ones.

### Escalated / skipped

Nothing new escalated. The three remaining `propose` candidates (Codex `/goal`
headless drivability, Codex/opencode cost parsing, flagship gif) were already
escalated in prior runs and stay blocked on real-CLI observation / interactive
recording work.

---

## Run Summary (2026-06-18, second run)

Autonomous improvement loop — 8 tasks completed.

### Landed

| Hash | Description |
|------|-------------|
| `29830fd` | test: add direct unit tests for reflect_on_failure (9 tests) |
| `75cd572` | fix: render_rich now shows diffstat; test plain render diffstat branch |
| `3aaab09` | test: add coverage for cmd_verify, cmd_propose --json, cmd_lessons --clear/--prune |
| `8e56509` | test: verify from_todos ignores TODO inside string literals |
| `1a2d4aa` | test: cover malformed package.json falling through in detect_verify |
| `36ce16c` | test: cover codex/opencode reflect() success and non-zero-exit paths |
| `838cabe` | test: cover on_iteration in delegate path + cmd_run with no verify |
| `1230b53` | build: add pytest to dev dependency group |

Notable: the `render_rich` fix (75cd572) was a real gap — the CLI's rich
summary omitted the diffstat block that the plain-text renderer already had.
A successful run with code changes would show no summary of what changed.

`reflect_on_failure` (29830fd) had zero direct tests despite being a
critical path — lessons are written here. All 9 new tests are offline.

Test count: 111 → 134 passed (23 new tests, all offline/sub-second).
All commits: `pytest -q` and `ruff check` clean before push.

---

## Run Summary (2026-06-18)

Autonomous improvement loop — 8 tasks completed.

### Landed

| Hash | Description |
|------|-------------|
| `4dadd63` | feat: add setup.cfg to zero-config verify detection |
| `948ce60` | refactor: remove unused BudgetTracker methods (cap_reached, remaining_usd, status) |
| `cc56c0a` | test: add patience config roundtrip coverage |
| `4750468` | test: cover on_iteration callback in run_loop |
| `d27276f` | test: cover TimeoutExpired path in run_verify |
| `604a480` | fix: from_lint output-format bug (--quiet → --output-format concise --quiet) + tests |
| `36ac826` | test: add missing detect_verify coverage for Cargo.toml |
| `65f31f3` | test: cover pytest.ini and tox.ini detection rules |

Notable: the `from_lint` fix (604a480) was a real bug — ruff's `--quiet` flag
switches to the annotated "full" output format, which the regex parser in
`propose.from_lint` could not read. In a repo with lint violations, `propose`
would have silently returned no lint candidates. Fixed by switching to
`--output-format concise --quiet`.

Test count: 102 → 111 passed (9 new tests, all offline/sub-second).
All commits: `pytest -q` and `ruff check` clean before push.

## Run Summary (2026-06-18, fourth run)

Autonomous improvement loop — 1 task landed.

### Landed

| Hash | Description |
|------|-------------|
| `e78f2ca` | fix: stop propose flagging capability-guarded skips as fix-me |

`propose` was surfacing the project's own `tests/test_propose.py:117`
(`if shutil.which(...) is None: pytest.skip("ruff not available")`) as a
"fix-me skip" every run — a recurring false positive. A `pytest.skip()`
reached only under an `if`/`elif` guard is a conditional skip (the test runs
when the guard is false, the normal CI case), i.e. intentional capability/
platform-gate infrastructure, not rot. `from_skipped_tests` now excludes that
inline-skip case, generalizing the prior env-var opt-in exclusion. Declarative
`@pytest.mark.skip` and unconditional inline skips are still surfaced; covered
by two new tests.

### Not done (escalation / out of scope)

The remaining `propose` candidates are the three `docs/STATUS.md` "## Next"
items: confirm whether Codex `/goal` is headlessly drivable, parse cost from
`codex exec --json` / `opencode run -f json`, and record the flagship gif.
All require observing real external-CLI output formats or recording media that
cannot be verified offline — escalate-don't-guess. They are already tracked in
STATUS.md, so no further action this run.

Test count: 111 → 113 passed (2 new tests, offline/sub-second).
`pytest -q` and `ruff check` clean before push.

## Run Summary (2026-06-19)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest -q` 113 passed, `uv run ruff check`
clean. `uv run looptight propose` surfaced a single candidate — STATUS.md "##
Next" item 3, recording the flagship gif (same command across agents plus a
lesson-dependent second task). That requires running real external agents and
capturing media that cannot be observed or verified offline (escalate-don't-
guess); it is already tracked in STATUS.md. The earlier "## Next" items (Codex
`/goal` headless drivability, Codex/opencode cost parsing) remain resolved/
deferred there. No lint or test-rot candidates remained after prior runs. Made
no code changes this run.

## Run Summary (2026-06-19, later)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest -q` 113 passed, `uv run ruff check`
clean. `uv run looptight propose` surfaced a single candidate: STATUS.md "##
Next" item 3 (record the flagship gif — same command across agents plus a
lesson-dependent second task). That requires running real external agents and
capturing media that cannot be observed or verified offline (escalate-don't-
guess); it is already tracked in STATUS.md. The prior skipped-test candidates
no longer appear — they were intentional opt-in/platform skips and the proposer
already excludes them. Made no code changes this run.

## Run Summary (2026-06-19, third)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest -q` 113 passed (1 skipped), `uv run
ruff check` clean. `uv run looptight propose` surfaced a single candidate:
STATUS.md "## Next" item 3 (record the flagship gif — same command across
agents plus a lesson-dependent second task), which requires real external-agent
runs and media capture that cannot be verified offline (escalate-don't-guess);
already tracked in STATUS.md. A skeptical read of the (small, mature) source
tree turned up no genuine, verifiable bug or simplification worth a diff.
Manufacturing a refactor or padding tests here would violate the run's idle-is-
success rule. Made no code changes this run.

---

## AUDIT (2026-06-19)

Reviewer: independent checker agent. Previous AUDIT marker: `045e1e2`.
Reviewed 1 commit from `675c393`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `675c393` | docs: record idle improve run 2026-06-19 (no actionable work) |

### Verdict: clean; no new concerns

**`675c393` — docs only, correct in substance:**
Appends a fourth idle-run summary to REVIEW-QUEUE.md. No code changes. The
proposer surfaced only the flagship-gif task (already escalated, correctly
skipped). Content is consistent with prior idle-run summaries.

**Recurring docs inaccuracy (noted, not re-flagged):** The run summary again
cites `113 passed` while the actual ground truth is `175 passed, 1 skipped`.
This has been flagged in prior audits; the actual gate always runs fresh and
the discrepancy reflects a stale session baseline in the improve agent. No
code is affected; the concern remains on record from earlier entries.

## Run Summary (2026-06-19, fourth)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest` reports **175 passed, 1 skipped**
(env-gated e2e), `uv run ruff check` clean. (Earlier idle-run summaries cited
"113 passed"; that figure was stale from a prior session and is corrected here,
per the auditor's recurring note.) `uv run looptight propose` surfaced a single
candidate: STATUS.md "## Next" item 3 (record the flagship gif — same command
across agents plus a lesson-dependent second task). That needs real external-
agent runs and media capture that cannot be observed or verified offline
(escalate-don't-guess); it is already tracked in STATUS.md. A skeptical read of
the small, mature source tree (2.7k LOC, all spec features ✅ except deferred
F3 ACP) found no genuine bug or simplification worth a diff. Made no code
changes this run.

---

## AUDIT (2026-06-19, fourth)

Reviewer: independent checker agent. Previous AUDIT marker: `5850632`.
Reviewed 2 commits from `675c393` through `b9eaf33`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `675c393` | docs: record idle improve run 2026-06-19 (no actionable work) |
| `b9eaf33` | docs: record idle improve run 2026-06-19 (no actionable work) |

### Verdict: clean; recurring stale-count inaccuracy self-corrected

**`675c393` — docs only, correct in substance:**
Another idle improve run. Proposer surfaced only the flagship-gif task
(already escalated, correctly skipped). Run summary again cited `113 passed`
(stale session baseline) — the pattern flagged in prior audits.

**`b9eaf33` — docs only; self-corrects the stale baseline:**
Fourth idle improve run. The agent explicitly acknowledges the auditor's
recurring note and corrects the count to `175 passed, 1 skipped`. No code
changes. Proposer again surfaced only the flagship-gif deferred task.

The long-standing "113 passed" inaccuracy is now resolved: the improve agent
updated its internal baseline and the current summary is accurate. No open
concerns remain from prior audits. No code was modified in either commit.

## Run Summary (2026-06-19, fifth)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest` reports **175 passed, 1 skipped**
(env-gated e2e), `uv run ruff check` clean. `uv run looptight propose` again
surfaced a single candidate: STATUS.md "## Next" item 3 (record the flagship
gif — same command across agents plus a lesson-dependent second task). That
needs real external-agent runs and media capture that cannot be observed or
verified offline (escalate-don't-guess); it is already tracked in STATUS.md.
The last several commits on main are docs-only idle/audit entries; the source
tree is unchanged and mature (all spec features ✅ except deferred F3 ACP). A
skeptical read found no genuine bug or simplification worth a diff. Made no
code changes this run.

---

## AUDIT (2026-06-19, fifth)

Reviewer: independent checker agent. Previous AUDIT marker: `24a1c93`.
Reviewed 1 commit from `966f4f6`.

### Test and lint gate

`uv run pytest`: 175 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `966f4f6` | docs: record idle improve run 2026-06-19 (no actionable work) |

### Verdict: clean; no concerns

**`966f4f6` — docs only, accurate:**
Appends the fifth idle-run summary to REVIEW-QUEUE.md. No code changes.
The improve agent correctly reports 175 passed (the stale `113` baseline is
now fixed, as noted by the fourth audit). Proposer surfaced only the
flagship-gif task — still correctly escalated. Content is self-consistent and
accurate. No open concerns from prior audits remain; the long-standing stale
test-count inaccuracy was resolved in `b9eaf33` and has stayed corrected
through this run.

## Run Summary (2026-06-20)

Autonomous improvement loop — no changes: nothing safe and valuable to do.

Baseline green on entry: `uv run pytest -q` reports **175 passed, 1 skipped**
(env-gated e2e), `uv run ruff check` clean. `uv run looptight propose` found
no candidate tasks ("clean tree"). No open GitHub issues or PRs. No
`TODO`/`FIXME`/`HACK`/`XXX` markers in `src/`. STATUS.md shows every spec
feature ✅ except the deliberately deferred F3 (ACP, post-v1); the remaining
"## Next" items are either resolved or the flagship-gif task that needs real
external-agent runs and media capture that cannot be observed or verified
offline (already escalated/tracked). A skeptical read of the source tree found
no genuine bug or simplification worth a diff. Made no code changes this run.

---

## AUDIT (2026-06-20, ninth)

Reviewer: independent checker agent. Previous AUDIT marker: `8f4f7fd` (eighth audit).
Reviewed 1 commit from `d191067` (the only commit since the eighth audit).

### Test and lint gate

`uv run pytest`: 229 passed, 1 skipped (env-gated e2e — correct).
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `d191067` | docs: record idle improve run 2026-06-20 (no actionable work) |

### Verdict: clean; one minor documentation inaccuracy flagged

**`d191067` — idle-run log entry, correct in spirit:**
A docs-only entry recording an improve run that found nothing to do. No code
was changed. The commit is appropriate and in-scope.

**Minor concern — test count mismatch in logged baseline (low severity):**
The improver's entry records "175 passed, 1 skipped" as the baseline. The
actual count — confirmed by this reviewer and consistent with the eighth
audit — is **229 passed, 1 skipped**. The 54-test discrepancy suggests the
improver ran `uv run pytest` without fully installing dev extras (e.g., without
`uv pip install -e ".[dev]"` or in an environment where some test files were
not discovered). This does not affect code correctness; it is a documentation
inaccuracy in the log.

**Suggested fix:** Ensure the improver's startup installs with `[dev]` extras
and verifies the test count against the previous audit before recording the
baseline.

No reverts required. No open concerns from prior audits remain unaddressed.

---

## Run Summary (2026-06-20, improver — idle + stale-clone correction)

Setup: `uv pip install -e ".[dev]"`; `uv run pytest` → 229 passed, 1 skipped
(env-gated e2e — correct); `uv run ruff check` → clean. **Main is GREEN.**

**No code changes this run.** `uv run looptight propose` reported "No candidate
tasks found from repo signals (clean tree)." Nothing safe and valuable to do;
per idle-is-success, no work was manufactured.

**Self-inflicted noise — corrected within the run (for the auditor's awareness):**
The session started with a *stale local clone*: `HEAD` was detached at the true
remote tip `468df65`, but the local `main` / cached `origin/main` ref still
pointed at an old, disjoint `211a31d` line (the remote `main` had earlier been
force-updated `211a31d`→`468df65`). Before fetching, I mis-read this as a real
divergence and over-reacted: opened issue #1 and pushed a backup branch
`recovered/improve-line-468df65`. A `git fetch` then showed `origin/main` was
already `468df65` (no divergence, no data-loss risk). I closed issue #1 as a
false alarm with a correction. **Lesson: always `git fetch` and validate
remote-tracking refs before any divergence analysis.**

**Leftover needing manual cleanup:** branch `recovered/improve-line-468df65`
(identical SHA to `main`) could not be deleted — push-delete returns `403` in
this environment and no delete-branch tool is exposed. Please delete it manually.

---

## AUDIT (2026-06-20, tenth)

Reviewer: independent checker agent. Previous AUDIT marker: `468df65` (ninth audit).
Reviewed 1 commit since the ninth audit: `b21f499`.

### Test and lint gate

`uv run pytest`: 229 passed, 1 skipped (env-gated e2e — correct). Count unchanged from ninth audit.
`uv run ruff check`: all checks passed.
**Main is GREEN.**

### Commits reviewed

| Hash | Subject |
|------|---------|
| `b21f499` | docs: record idle improve run 2026-06-20 (no actionable work; stale-clone correction) |

### Verdict: clean; one informational note

**`b21f499` — idle-run docs entry, correct and properly scoped:**
Pure REVIEW-QUEUE.md documentation commit; no code changed. Records an idle
`looptight improve` run where `propose` found no candidate tasks (clean tree) —
correct idle-is-success behaviour. Also documents a self-corrected stale-clone
misdiagnosis: the improver initially misread a detached-HEAD / stale-ref situation
as a real divergence, opened a GitHub issue and pushed a backup branch before a
`git fetch` revealed no actual divergence. The issue was closed as a false alarm
and the lesson recorded (always fetch before divergence analysis). The write-up is
honest, clear, and the lesson is sound.

**Informational note (not a concern, recorded for continuity):**
The leftover branch `recovered/improve-line-468df65` mentioned by the improver
cannot be deleted by agents (push-delete returns 403). A human owner should delete
it from the GitHub UI. There is no code impact; the branch is identical to `main`.

No reverts required. No open concerns from prior audits remain unaddressed.
