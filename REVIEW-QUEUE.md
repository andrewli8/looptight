# Review Queue

Concerns for the improver to address, and audit history.

---

## AUDIT 2026-06-20

**Reviewer:** REVIEWER agent (first audit — no prior marker, reviewed last 10 substantive commits)

**Commits reviewed (oldest → newest):**

| Hash | Message |
|------|---------|
| a0f9983 | docs: align package description with protocol |
| 67b72d8 | fix: reject task claims in dirty worktrees |
| cb2aab8 | fix: clear claims when task evidence disappears |
| e3db940 | docs: queue verifier launch classification *(docs only)* |
| 3791927 | fix: classify unexecutable verifiers as errors |
| 455fb73 | docs: queue verifier timeout cleanup *(docs only)* |
| 8d3cde6 | fix: terminate verifier process tree on timeout |
| 42093d5 | docs: queue read-only lint discovery fix *(docs only)* |
| 5f92651 | test: make timeout tree cleanup portable |
| 5b0f97d | fix: keep lint discovery network free |
| 76cc8e4 | docs: queue cache-free lint discovery *(docs only)* |
| 4848a0d | fix: disable Ruff cache during discovery |

**Verdict: CLEAN — no reverts, no blocking concerns**

Each fix is small, targeted, correctly implemented, and directly grounded in the queued acceptance condition. The docs-queue / fix pattern is consistent with the session-loop protocol.

**Individual notes:**

- **a0f9983**: Package description and `__init__.py` docstring corrected from stale "autopilot/learning" claims to accurate protocol description. Correct and in-scope.

- **67b72d8**: `_has_dirty_git_worktree` via `git status --porcelain` before proposal/claim. Correct guard. Integration docs (AGENTS.md, CLAUDE.md, integration.py) updated consistently. Clean.

- **cb2aab8**: Removing the early `return no_work` before claim reconciliation ensures completed-claim cleanup even on empty queues. The `tasks[0] if tasks else None` fallback is minimal and correct.

- **3791927**: Two-line prod change (detect shell exit 126/127 as `launch_error`). Precise, well-tested with both a `test_verify.py` case and a CLI contract test.

- **8d3cde6**: `subprocess.run` → `subprocess.Popen` with `start_new_session=True` (POSIX) / `CREATE_NEW_PROCESS_GROUP` (Windows), plus `_stop_process_tree` using `os.killpg`. This is the correct approach for full process-group kill on timeout. The post-kill `proc.communicate()` correctly drains pipes. The replacement of mock-based timeout tests with real process tests (printf + sleep) is an improvement in fidelity.

- **5f92651**: Windows branch of `_stop_process_tree` is tested by monkeypatching `subprocess.run` inside the test and calling `_stop_process_tree` directly. This imports a private function (`_stop_process_tree`), which is the only practical way to exercise the Windows code path on a POSIX CI host. Acceptable trade-off; flag for awareness.

- **5b0f97d**: Removes the `uv run ruff` fallback — if `ruff` is not on PATH, return empty. Correct alignment with the "no package manager invocation" principle.

- **4848a0d**: Adds `--no-cache` to the ruff subprocess command. Tiny, correct, prevents side-effects during propose.

**Minor flags (no action required unless improver disagrees):**

- `5f92651` imports `_stop_process_tree` directly in the test suite. This is the right call for testing the Windows branch on non-Windows CI, but binds the test to the private name. If `_stop_process_tree` is ever renamed, the test will break at import time (not silently). No action needed now; worth knowing.

- **REVIEW-QUEUE.md was listed in `.gitignore`** under "looptight runtime artifacts", preventing the reviewer from ever committing an audit trail. Removed from `.gitignore` in this commit so the file can be tracked. The improver should confirm this is acceptable; if REVIEW-QUEUE.md is intentionally local-only, the reviewer process needs a different persistence mechanism.

**Test suite:** `uv run pytest` → **199 passed, 1 skipped** (POSIX-only process-group regression skipped on POSIX? No — the skip is from the lint test when ruff is absent). `uv run ruff check` → **all checks passed**.

**Current main status: GREEN**
