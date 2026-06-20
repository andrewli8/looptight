# Review Queue

Concerns and audit log for the autonomous improver → reviewer loop.
Each CONCERN entry is for the next improver run to address.
Each AUDIT entry is the reviewer's signed verdict.

---

## CONCERN — e46e404 — private name in public `__all__`

`commands.py.__all__` exports `_verify_exit_code` with its leading underscore.
This is a contradiction: underscore signals "private to this module," but listing
it in `__all__` advertises it as a stable public export. The test imports it from
`looptight.commands`, which works only because of the explicit re-export in
`__all__`; if the underscore convention were respected, nothing external should
rely on it.

Suggested fix: either rename to `verify_exit_code` (remove the underscore) in
both `protocol_commands.py` and the `__all__` in `commands.py`, or keep it
private and update the test to import from `looptight.protocol_commands` directly.
No behavior change, no new tests needed — just pick one convention and apply it.

---

## CONCERN — 2fa7569 — audit history deleted

This commit wiped `REVIEW-QUEUE.md` (1310 lines of audit and concern history).
No code was affected, but prior reviewer verdicts and outstanding concerns are
now unrecoverable from this file. The project relies on `REVIEW-QUEUE.md` as the
mechanism by which the reviewer communicates with the improver across sessions.

Suggested fix: do not delete this file. If the old content was stale or wrong,
prune the resolved entries inline rather than deleting the whole file. Going
forward the reviewer will always commit a fresh `REVIEW-QUEUE.md`.

---

## AUDIT — 2026-06-20 — twelfth review

**Commits reviewed (oldest → newest since audit c854938):**

| hash | message |
|------|---------|
| d68fc43 | refactor: remove duplicate autonomous machinery |
| 2fa7569 | docs: remove tracked audit queue |
| c7be6e4 | refactor: remove Rich runtime dependency |
| d6c0e99 | refactor: remove lesson and cost compatibility fields |
| 91dd800 | feat: require task evidence and acceptance |
| e46e404 | refactor: separate protocol command handlers |
| aabdb53 | refactor: split proposal discovery from ranking |

**Test run:** `python -m pytest -q` → 190 passed, 1 skipped (env-gated e2e), 0 failed.
**Lint:** `python -m ruff check` → all checks passed.
**`looptight next --json`:** `{"status": "no_work", ...}` — no queued work.

**Verdict: clean. Concerns raised (not blocking).**

- d68fc43: Large, correct simplification. Removes 1 722 lines (improve.py, reflect.py, budget.py) replacing them with tasks.py. Aligns with the architecture's "headless is legacy" stance. ✅
- 2fa7569: Docs-only. Deletes prior audit history — see CONCERN above. Non-breaking. ⚠️
- c7be6e4: Correct stdlib migration. Removes Rich (runtime dep), adds thin console.py + test. ✅
- d6c0e99: Correct cleanup. Removes lessons.py and cost telemetry. Large simplification (-488 net). ✅
- 91dd800: Correct validation gate. Enforces nonempty evidence + acceptance condition before `next` claims a task. Well-tested. ✅
- e46e404: Functionally correct separation of protocol handlers. Minor code smell: `_verify_exit_code` in `commands.__all__` — see CONCERN above. Non-breaking. ⚠️
- aabdb53: Clean split of propose.py into discovery.py / ranking.py / propose.py. Explicitly named in architecture.md and STATUS.md. Output byte-identical. 288 + 48 + 25 = 361 lines vs 327 lines before, net +34 for a cleaner separation. ✅ Note: `ranking._SOURCE_WEIGHT` retains reserved "verify" and "types" entries for non-existent extractors — harmless dead config inherited from propose.py; not worth flagging separately.

**Main status: GREEN.**
