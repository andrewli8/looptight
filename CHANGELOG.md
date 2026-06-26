# Changelog

All notable changes to looptight are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims for
[semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- `propose --source <type>` filters the task queue by signal type, and
  `propose --eval` scores the generated `## Next` batch on groundedness and
  diversity.
- `init` warns when the detected verify command is a weak gate (lint-only or
  none), so a loop is not gated by a test command that proves nothing.
- `doctor` is scriptable: a readiness exit code and `--json` for CI gating.
- When value-aware stopping cuts a headless `run` short, the summary now explains
  why: the failures that never cleared across the attempts plus the progress
  trajectory, instead of a bare "stuck, worth a human look."
- `run --json` emits the versioned run result (stop reason, per-iteration verdicts,
  diffstat) including an `escalation` object, closing the gap where `run` was the
  only command without `--json`.
- `verify --patience N` brings value-aware stopping to the session-native path: it
  persists the progress trajectory between calls (Git-private, per-worktree) and
  adds an additive `stall` object to `verify --json` with the stall decision and,
  when stuck, the escalation evidence. Off by default; the default verifier
  contract is unchanged.

### Changed

- `status` is goal-aware: it points at `goal next`, surfaces the active goal, and
  reports the generated queue's groundedness as a self-improvement signal.
- `next` and `propose` human output guide a new contributor through implement →
  verify → commit, and toward `next`/`goal` when the queue is empty.

### Fixed

- Readiness (`doctor`/`status`) no longer reports `task_sources: missing` when a
  repo has discoverable TODOs or skipped tests — looptight's primary task source.
  A repo with real discoverable work now reads `readiness: ready` instead of a
  confusing `partial` that told the user to "add grounded tasks" they already had.
- Python TODO/FIXME and skipped-test discovery is now layout-agnostic: it scans
  the whole project (pruning vendored and cache dirs) instead of only `src/` and
  `tests/`, so a flat package (`mypackage/`) or top-level modules — the majority of
  Python layouts — no longer report `NO_WORK` when real markers exist.

- `read_goal` and the read-only view's `read_state` return safe defaults on a
  non-UTF-8 file instead of crashing; `write_goal` and `write_state` no longer
  leave a stale `.tmp` behind when a save fails.
- Truncated verifier output stays within the documented byte cap.
- The README logo renders on PyPI as well as GitHub (a tight PNG served by an
  absolute URL, replacing the relative SVG that PyPI could not resolve).

## [0.1.0]

First release: a test-gated work loop that runs inside a coding agent's session.

- `next` and `verify`: the session-native loop, with no model or network calls.
- Grounded task discovery from real repo signals (TODO/FIXME, skipped tests, lint,
  the `## Next` list, configured task files); polyglot across Python and JS/TS.
- `propose`: the ranked task queue; and `doctor`: the detected agent, verify
  command, and adapters.
- `goal` mode: a vision-driven 0-to-1 build, one verify-gated increment at a time.
- Unattended modes: `run`, `swarm`, and `daemon`, with a repo-private SQLite
  coordinator for sharing one queue across sessions.
- Observability: `status`, `status --watch`, `ui`, and `statusline`.
- Integrations: `install-skill`, `init --integrate`, a pre-commit hook, and a
  composite GitHub Action.
- Zero third-party runtime dependencies; the package runs on the standard library.
