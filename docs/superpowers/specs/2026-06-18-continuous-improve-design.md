# Continuous improve command

Date: 2026-06-18
Status: approved by direction

## Goal

Add `looptight improve`, an explicit autonomous mode that repeatedly discovers
and executes one repository improvement at a time until the user interrupts it,
a session spend threshold is reached, or the provider refuses further work.
Ordinary `looptight run` remains a finite verify-gated goal run.

## User experience

```bash
looptight improve                 # use provider usage limits
looptight improve --budget 10     # add a session-wide USD spend threshold
looptight improve --push          # push each verified commit
```

The existing config budget remains the per-task stop threshold. `improve
--budget` is separate and cumulative across tasks. When an adapter cannot
report USD cost, the CLI states that the session threshold cannot be enforced
for that provider and continues until the provider stops accepting calls.

Ctrl-C stops cleanly after the current subprocess receives the interrupt. A
provider nonzero exit stops the session and must never be reported as success
merely because the repository's verification command was already green.

## Continuous cycle

1. Require a Git repository with a clean working tree and a verify command.
2. Read grounded candidates from `propose`, skipping candidates already tried
   in the current session.
3. When grounded candidates are exhausted, ask the coding agent to inspect the
   repository and implement exactly one high-value, evidence-backed, verifiable
   improvement. Each audit prompt names prior no-op or failed attempts so the
   agent explores a different area.
4. Execute the task through the existing `run_loop` and its per-task iteration,
   patience, reflection, checkpoint, and budget guardrails.
5. If verification passes and the tree changed, commit the coherent change.
   Push it when `--push` is set.
6. If verification passes with no diff, record a session no-op and continue.
7. If a task cannot be verified, restore the clean pre-task checkpoint and
   remove only untracked files created during that task, then continue.
8. Repeat without a no-work stop condition.

## Safety

- `improve` never starts on a dirty tree, so task rollback cannot erase
  pre-existing user work.
- Exactly one task runs at a time.
- Only verified diffs are committed; pushing requires explicit `--push`.
- No force-push, merge, dependency auto-install, or destructive branch change.
- Failed/no-progress task edits are rolled back before another task starts.
- Commit and push failures stop the session with a nonzero result.
- Agent and provider failures are first-class errors, not verification success.
- Session history prevents repeatedly selecting the same grounded candidate.

## Architecture

Create `src/looptight/improve.py` for orchestration and Git operations. Keep the
CLI responsible only for argument/config resolution and progress rendering.
`run_improve` accepts injected proposal, run, and command collaborators so the
continuous control flow is testable without agents, network access, or real
remote pushes.

Extend `RunResult` with optional error text. Both supplied and delegated loop
paths stop with `StopReason.ERROR` before verification when an adapter reports
`ok=False`. This fixes normal runs as well as enabling provider-limit detection
for `improve`.

## Verification

- Loop tests cover supplied and delegated adapter failures on an already-green
  repository.
- Improve tests cover clean-tree refusal, grounded-to-audit task transition,
  no-op continuation, cumulative reported-cost stopping, rollback after an
  unverified task, commit/push behavior, command failure, and Ctrl-C handling.
- CLI tests cover parser defaults, explicit session budget, `--push`, and the
  warning for adapters that report no USD cost.
- Full pytest and Ruff gates remain required before every commit.
