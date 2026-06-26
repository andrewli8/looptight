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

- The coordinator is no longer a readiness requirement. A solo loop runs on file
  claims, so `doctor` now reports `setup: ready` and `readiness: ready` for a
  repo with verify + git + agent + a task source even when the coordinator is
  inactive; `migrate` is offered as an optional hint (cross-session sharing)
  rather than a blocking `setup next`. The coordinator is still a reported check.
- `status` is goal-aware: it points at `goal next`, surfaces the active goal, and
  reports the generated queue's groundedness as a self-improvement signal.
- `next` and `propose` human output guide a new contributor through implement →
  verify → commit, and toward `next`/`goal` when the queue is empty.

### Fixed

- `revert --yes` no longer claims it "reverted" on a clean tree. It ran
  `git checkout HEAD -- .` unconditionally and always reported success, so on an
  already-clean tree a user was told their changes were undone when nothing
  happened. It now checks for tracked changes first and reports "nothing to
  revert" when the tree is clean, still noting any untracked files.
- On a `verify --patience` stall, the human `next:` step no longer advises
  "continue fixing." A stall means the current approach is not progressing, so it
  now points at a different approach or human review, matching the stall signal's
  purpose instead of undercutting it.
- `next` no longer prompts idea generation when the queue is merely busy. It
  attached the `generate_ideas` directive on every `no_work`, even when real
  candidates existed but were all leased by other live runs — so a second session
  finding the queue busy was told to "generate grounded tasks," inflating the
  queue with duplicates. The directive (and the "queue empty" message) now appear
  only when there are genuinely no candidates; a busy queue reports a plain
  `NO_WORK`.
- Swarm change-scoping (`_task_paths`) now resolves a markdown-backticked
  evidence anchor to its bare file. It parsed the evidence field with its own
  ad-hoc regex, so a `` `path:line` `` anchor (which the task summary now emits)
  kept its backticks and the real file was dropped from the set of paths a worker
  may change. It now routes through the shared `evidence_refs` /
  `strip_anchor_decoration`, the last evidence parser to do so.
- `goal check` no longer fails silently. It exited 1 with no output both when no
  goal was set and when a goal had no `--done` check, so a user could not tell
  whether the goal was incomplete or simply uncheckable (and a `/loop until:
  looptight goal check` with no done-check would loop forever with no hint). It
  now prints which case it is and how to fix it, still exiting 1.
- `init --integrate` is now idempotent across both managed blocks. The session
  block stripped the blank line before the goal block, which the goal install
  then restored, so each block rewrote the file on every run — `init --integrate`
  always reported "installed" instead of "already installed", and both installers
  falsely reported a change. The blocks are now laid out canonically (one blank
  line between sections) so re-running is byte-stable.
- `init` no longer contradicts itself when no test command is detected. It used
  to print "Could not detect a test command — set `verify` in the config" while
  the file it wrote already contained `verify = "pytest -q"` (render_config's
  default). The message now names the default it wrote and says to replace it,
  and the default is a shared constant so the file and the message cannot drift.
- The grounding gate now resolves an `Evidence:` anchor wrapped in markdown
  backticks (`` Evidence: `src/app.py:10` ``). Previously the backticks were
  treated as part of the path, so the anchor did not resolve and a real,
  grounded task was silently dropped — `next` returned `no_work` and the loop
  stalled despite a valid task in `## Next`. Backticked anchors are idiomatic
  (this project's own `docs/STATUS.md` writes them that way, as do LLM-generated
  tasks), so this affected the common case. The swarm planner's own grounding
  check had the same defect and is fixed alongside it.
- `detect_verify` no longer claims `npm test` for the `npm init` placeholder
  script (`echo "Error: no test specified" && exit 1`). That command always
  fails, so a fresh JS repo would get a verify that can never pass — the loop
  would stall before a single test was written. The placeholder now falls
  through to `None`, so `init` reports no gate (and warns) instead.
- A lint idea's identity is now stable when the finding shifts lines. `idea_id`
  dropped only one trailing `:segment`, so a real `path:line:col` lint location
  kept its line number — a finding that moved (e.g. an import added above it)
  got a new identity, and the self-model and cooldown then failed to recognize a
  re-proposed lint idea. The full `:line:col` position is now stripped, matching
  the grounding check and `from_lint`'s own file-level dedup.
- `looptight migrate` no longer doubles its error prefix when a live legacy
  claim blocks activation (was `cannot activate the coordinator: cannot activate
  the coordinator: live legacy claims exist…`). The exception carries the reason;
  the command supplies the framing.
- The session-loop instructions (in installed `CLAUDE.md`/`AGENTS.md` and the
  Claude Code skill) now say to add generated `## Next` tasks as a *numbered*
  list. The discovery parser only reads numbered items, so an agent's natural
  `-` bullets were silently dropped — the loop then saw `no_work` and stalled
  despite freshly added tasks. The instruction now matches the parser.
- `.looptight.toml` with a leading UTF-8 BOM (common from Windows editors) now
  loads instead of failing with a cryptic `Invalid statement (at line 1, column
  1)`. The file is decoded BOM-tolerantly; plain UTF-8 is unaffected.
- TODO discovery no longer surfaces marker-prefixed compound words in prose
  (`# fixme-style naming`, `# todo-list helper`) as false-positive tasks. A marker
  must be followed by `:`, whitespace, or end of line.
- The grounding gate now applies to configured task-files, not only generated
  `## Next`. Previously, setting `tasks = ["docs/STATUS.md"]` (looptight's own
  config) made `next` claim a task whose `Evidence:` anchor did not resolve — a
  bypass of the anti-fabrication guarantee. A task claiming non-resolving evidence
  is now dropped regardless of source; unanchored tasks are still kept.
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
