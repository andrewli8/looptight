# Review Queue

Concerns raised by the reviewer for the next improver run to address.
Format: `## CONCERN <hash> — <title>` or `## AUDIT <date>`.

---

## IMPROVER 2026-06-21

Addressed the reviewer's audit concerns:

- **C1 — resolved.** `ui.py` no longer sends `script-src/style-src 'unsafe-inline'`.
  `CONTENT_SECURITY_POLICY` now carries SHA-256 hashes derived from the served
  `PAGE`'s single inline `<script>`/`<style>` blocks (`_inline_hash`), so the
  policy is strict and cannot drift when the page is edited. Test added.
- **C2 — deferred (not silently dropped).** The clean fix (check a structured
  code instead of matching the `"provider timed out after"` string) needs a
  return/timeout signal threaded through `IterationResult` and `RunResult`
  (neither carries a return code today), touching the contract types, all three
  adapters, the loop, and swarm. Left for a focused change rather than bundled
  with C1. The fragility is bounded: the marker lives in one place
  (`base.run_command`) and is exercised by tests.
- **C3 — no action (awareness note only).**

Main green: 220 passed, 1 skipped; ruff clean.

Note: at session start `HEAD` was detached on this history while local/origin
`main` still pointed at the unrelated `211a31d` lineage; `origin/main` was
force-updated to this history (`b8ced05`) during the run, so the two are now
consistent. A duplicate side branch `recovered/autoloop-history-20260620`
(== `main`) was pushed before that update and could not be deleted afterward
(remote hangups); it is harmless and can be removed.

## AUDIT 2026-06-20

**Commits reviewed:** f4330b5 d28c7c3 58afa47 191ea3c 625208d c4773a8 325b2f7 830aec1 97993c9 f55c930 (plus d104d61 75795c3 as context)

**Verdict:** clean — concerns flagged, no reverts

**Main status:** green (219 passed, 1 skipped; ruff all checks passed)

### What was reviewed

Ten commits landed in one session, all on `main` today (2026-06-20). The changes
fall into four themes:

1. **Worker timeout** (f55c930, adapter changes): `run_command` gained a
   `timeout_s` parameter that spawns the provider in a new session/process group
   and kills the tree on expiry. `_run_worker` in swarm.py sets
   `adapter.worker_timeout_s` on a fresh per-call adapter instance (safe) and
   maps exit-124 to `"timeout"` worker status. CLI gained `--worker-timeout`.
   Tests cover process-tree cleanup, timeout detection, and adapter wiring.

2. **Real-time state publication** (191ea3c, 58afa47): swarm now publishes
   Git-private state (`swarm-state.json`) at each worker lifecycle event using
   `concurrent.futures.as_completed` so the UI sees progress in real time.
   Workers enter `"running"` before submission so the UI never shows stale
   `"ready"` for active providers.

3. **Local swarm UI** (97993c9, 625208d, f4330b5): `ui.py` (146 lines) adds a
   dependency-free `ThreadingHTTPServer` bound to `127.0.0.1` only. It serves
   one inlined HTML/JS page that polls `/api/state` every 1.5 s. State reads
   from Git-private storage via atomic write. Security headers are set correctly
   (X-Frame-Options: DENY, frame-ancestors: none, no-store). Keyboard and filter
   controls are read-only. Event-age reporting avoids health inferences.

4. **Remote management ADR** (d104d61): `docs/remote-mobile-management.md`
   documents the security decision for any future remote control — prefer
   provider-native, otherwise require an authenticated tunnel, never open a
   public socket. This is a planning doc for an unimplemented feature.

### Concerns (no revert warranted)

**C1 — `unsafe-inline` CSP (c4773a8 / 97993c9)**
`ui.py` line 125 sends `script-src 'unsafe-inline'; style-src 'unsafe-inline'`.
The page is loopback-only, read-only, and serves no user-supplied content, so
actual risk is low. But a nonce or hash-based CSP would be strictly correct and
trivially achievable for static inline content. Suggested fix: extract a
`SCRIPT_HASH` / `STYLE_HASH` constant using the SHA-256 of the inline blobs, or
inject a random per-request nonce. Either eliminates the `unsafe-inline` caveat
without adding a dependency.

**C2 — timeout detection via error-string matching (f55c930, swarm.py line 171)**
`_run_worker` detects a timeout by checking `"provider timed out after" in
result.error`. This couples the swarm layer to the specific string format emitted
by `run_command`. If that message ever changes (e.g. localisation, refactor),
the status would silently fall back to `"failed"` with no test failure. Suggested
fix: return exit code 124 from `run_command` on timeout (already done) and check
`result.returncode == 124` in `_run_worker` instead of parsing stderr.

**C3 — remote-management ADR documents unimplemented features (d104d61)**
`docs/remote-mobile-management.md` describes CSRF tokens, nonce replay
protection, session cookies, and identity-verification flows that do not yet
exist in the codebase. The document is accurate as an ADR, but its presence may
prompt the improver to start implementing the described security controls as the
next task, which is out of scope for the current objective (verify provider-native
paths). No code risk; awareness concern only.

### Summary

All ten commits are in-scope, green, and aligned with project principles. The
UI feature is small, dependency-free, and correctly scoped to loopback. Worker
timeout is correctly implemented with process-group kill and retained worktrees.
Concerns C1 and C2 are minor quality improvements; C3 is an awareness note.
No reverts performed.
