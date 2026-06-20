# Self-improvement status

This is looptight's bounded running plan. Keep only the current objective,
validated results, and at most six executable tasks. Git history is the archive.

## Objective

Make looptight the smallest reliable validation and task protocol shared by
Codex, Claude Code, and OpenCode. The default path runs inside the user's
existing CLI session and makes no model or API calls of its own.

## Loop

1. Plan from repository evidence and user-facing friction.
2. Keep small tasks with observable acceptance conditions under `Next`.
3. Execute the highest-value task in the current agent session.
4. Require `looptight verify --json` to return `pass`.
5. Commit and push the coherent result, then update this file.
6. Stop successfully when `looptight next` returns `NO_WORK`.

## Validated

- `verify --json` schema v1 distinguishes pass, fail, timeout, and error.
- `next --json` schema v1 returns one grounded task or `NO_WORK`.
- Both protocols are provider-neutral and make no agent or network calls.
- Atomic task claims are shared privately across Git worktrees, recover after
  24 hours, and disappear when their source task is no longer grounded.
- `init --integrate` installs the same bounded session loop for Codex and
  OpenCode (`AGENTS.md`) and Claude Code (`CLAUDE.md`) without child agents.
- `status --json` reports validation readiness, workspace safety, claims, and
  the next action without running checks or changing state.
- `run` and `improve` refuse to launch agent CLIs unless `--headless` is
  explicit; current-session docs make no provider-billing promises.

## Next

1. Remove generated reflection, cost estimation, and duplicate continuous-loop
   machinery after compatibility warnings.
2. Remove the Rich runtime dependency and keep human and JSON output legible
   with the standard library.

## Rules

- Validation outranks activity: no evidence means `NO_WORK`, not a new audit.
- Only a valid task claim plus a passing verifier may authorize a commit.
- Never record idle runs, generated lessons, token consumption, or repeated
  review logs here.
- Replace completed tasks with validated outcomes; do not append a changelog.
