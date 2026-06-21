# Review Queue

Concerns raised by the reviewer for the next improver run to address.
Format: `## CONCERN <hash> — <title>` or `## AUDIT <date>`.

---

## CONCERN 897a854 — timeout detection via error-string matching (carried forward)

**Severity:** minor quality / low risk  
**Original source:** audit 2026-06-20 concern C2; deferred by improver in 2bef8a7;
REVIEW-QUEUE.md deleted in 897a854, so re-logged here to keep it in the trail.

`_run_worker` in `src/looptight/swarm.py` detects a timeout by checking
`"provider timed out after" in result.error`. This couples the swarm layer to
the specific string format produced by `run_command` in `adapters/base.py`. A
refactor or localization of that string would silently demote a timeout to a
generic failure with no test alarm.

**Suggested fix:** `run_command` already exits with code 124 on timeout. Check
`result.returncode == 124` in `_run_worker` instead of parsing stderr. Both
`IterationResult` and `RunResult` would need a `returncode` field — a small,
focused change that touches only the adapter contract and swarm.

---

## CONCERN 897a854 — potential infinite loop under --continuous --max-rounds 0

**Severity:** low (opt-in headless path only)

`run_continuous_swarm` loops while `max_rounds == 0 or rounds < max_rounds`. If
`plan_next_tasks` repeatedly returns `"planned"` but tasks are never successfully
claimed or integrated (e.g., every worker fails to claim), `run_swarm` returns an
empty worker list, the loop falls through to planning again, and repeats without
bound when `--max-rounds 0` (the default).

Requires `--continuous`, a broken claim path, and an always-succeeding planner —
an unlikely combination. CTRL+C works. But callers who assume "eventually
terminates" should be aware.

**Suggested fix:** Count consecutive empty-worker rounds and stop after N (e.g.,
3) with an informative error, or require `--max-rounds` when `--continuous` is
set.

---

## AUDIT 2026-06-21

**Commits reviewed:** 2bef8a7  897a854

**Verdict:** clean — two minor concerns flagged, no reverts

**Main status:** green (225 passed, 1 skipped; ruff all checks passed)

### What was reviewed

Two commits landed since the 2026-06-20 audit (b8ced05).

**2bef8a7 — fix: drop unsafe-inline from swarm UI CSP** (Claude, 2026-06-21 00:12 UTC)

Resolves reviewer concern C1. Replaces `unsafe-inline` in both `script-src`
and `style-src` with SHA-256 hashes derived at import time from the served `PAGE`
constant (`_inline_hash`). No new runtime dependencies (stdlib `hashlib` +
`base64` only). Hash computation is correct and can only drift if the inline
`<script>` or `<style>` content changes, which would cause the test to fail.
Test added verifies both the constant and the live HTTP header. In scope, correct,
minimal.

Minor observation: the test re-implements the same hash logic (`_expected_inline_hash`)
rather than asserting a known-good hex value. This means a symmetric bug in both
places would go undetected. Given the stdlib functions are well-established and
the test also exercises the live header path, the risk is acceptable but worth
knowing.

REVIEW-QUEUE.md was correctly updated (C1 resolved, C2 deferred with explanation,
C3 noted as awareness only).

**897a854 — feat: add continuous swarm planning** (andrewli8, 2026-06-21 01:01 UTC)

Adds `--continuous` / `--max-rounds` to `swarm`, implementing the architecture
documented in `architecture.md` ("With explicit `swarm --continuous`, the selected
provider CLI supplies one planning pass only after grounded work is exhausted").
In scope per SPEC and STATUS.

Key validation chain is correct:
- Planning occurs in an isolated Git worktree at `<git-common-dir>/looptight/planner/<token>`.
- Provider may only change `docs/STATUS.md`; any other file change is a hard rejection.
- Tasks must be 1–6, each with an `Evidence:` path to a real file and an
  `Acceptance:` clause; `docs/STATUS.md` is explicitly disallowed as evidence.
- Verifier runs twice: in the planner worktree, then again after merge to main.
- Merge is aborted on any failure; planner worktree is retained for inspection.

Tests are real (not padding): parser, grounded merge, self-referential rejection,
provider-committed plan, and multi-round continuous integration. All pass.

**Issues noted in 897a854:**
1. REVIEW-QUEUE.md was deleted. The improver had updated it in 2bef8a7 (C2
   deferred, C3 noted). The deletion by the human author erased the C2 concern
   from the audit trail. REVIEW-QUEUE.md is re-created here with C2 carried
   forward.
2. Concern C2 (timeout string matching) remains unresolved — noted above.
3. Minor infinite-loop risk under `--continuous --max-rounds 0` with consistently
   empty-worker rounds — noted above.

### Summary

Both commits are functionally correct, in scope, and dependency-free. The CSP fix
is a clean resolution of C1. The continuous swarm planning feature is
well-validated, conservatively gated (opt-in `--continuous`, evidence-checked,
verify-twice), and correctly documented. No reverts warranted. Two low-severity
concerns flagged for the next improver run.
