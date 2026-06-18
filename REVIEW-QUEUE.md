# Review Queue

Items that need a human decision or external verification before they can land.

---

## Escalated (2026-06-18)

### Cannot observe external CLI output formats

**Codex `/goal` headless drivability**
Cannot confirm whether `codex /goal` can be driven headlessly (`codex exec /goal …`).
If it can, `CodexAdapter.supports_native_loop` should be set to `True` and
`drive_native_loop` implemented. Blocked on running a real Codex CLI session.
Source: `docs/STATUS.md` → Next #1.

**Codex/opencode cost parsing**
`codex exec --json` and `opencode run -f json` output formats are unconfirmed.
Implementing `cost_usd` parsing (so the dollar ceiling binds on all three adapters,
not just Claude) requires observing real output. Blocked on real CLI access.
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
Recording a gif of the same command across agents (docs/STATUS.md Next #3) is a
human-performed documentation task, not a code change.

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
escalated in prior runs and stay blocked on real-CLI observation / human work.

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
