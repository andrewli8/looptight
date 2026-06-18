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

### Deferred non-goal

**Flagship gif**
Recording a gif of the same command across agents (docs/STATUS.md Next #3) is a
human-performed documentation task, not a code change.

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
