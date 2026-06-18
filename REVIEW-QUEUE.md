# Review Queue

Items blocked on unavailable evidence or a decision that cannot be derived
safely from the repository. Autonomous runs skip these and continue with the
next actionable task.

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
