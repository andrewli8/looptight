# looptight

The same validation-gated task loop inside Codex, Claude Code, or OpenCode.
Looptight coordinates the agent session you already have; it does not need to
launch another agent.

## Install and integrate

```bash
uvx looptight init --integrate
```

`init` detects the project verification command and writes `.looptight.toml`.
`--integrate` installs one bounded instruction block in `AGENTS.md` for Codex
and OpenCode and `CLAUDE.md` for Claude Code.

The installed native-session loop is:

```text
next → implement → verify → review → update status → commit → repeat
```

It stops successfully when `next` returns `NO_WORK`. The current agent CLI owns
authentication, models, context, and usage limits. `next`, `verify`, and
`status` make no model or network calls.
The installed package has no third-party runtime dependencies.

## Verification is the contract

```toml
# .looptight.toml
verify = "pytest -q"
```

Exit zero is the only passing verdict. For integrations and scripts:

```bash
looptight verify --json
```

The versioned result distinguishes `pass`, `fail`, `timeout`, and `error`.
Command exit codes are `0` for pass, `1` for a valid negative verdict, and `2`
for configuration or validator-execution errors.

## Session commands

```bash
looptight next --json    # atomically claim one grounded task, or NO_WORK
looptight verify --json  # run the objective project contract
looptight status --json  # inspect validation, workspace, claims, and next action
looptight propose        # inspect the ranked grounded task queue
```

Tasks come from concrete repository signals such as the bounded `Next` list in
`docs/STATUS.md`, source TODOs, skipped tests, and lint findings. Empty queues do
not generate speculative audits. A dirty Git worktree returns a machine-readable
error before proposal discovery or claim mutation.

In Git repositories, task claims live under Git's private common directory.
They are shared across worktrees, never appear as tracked files, and expire
after 24 hours. Parallel sessions should use separate worktrees.

## Optional headless compatibility

```bash
looptight run --headless "fix the failing tests"
```

`run` is an explicit compatibility path that launches the selected provider
CLI and applies the same verifier after each iteration. Looptight does not claim
how provider CLIs authenticate or bill child processes. The former `improve`
orchestrator is deprecated; use the native-session loop above.

## Isolated headless swarm

```bash
looptight swarm --headless --agent codex --workers 4 --push
# or: --agent claude
```

The deterministic manager claims up to one grounded task per worker, creates an
isolated Git worktree and branch for each, runs workers concurrently, and merges
successful branches one at a time only when the project verifier still passes.
The hard limit is 50 workers; start with a small value because provider limits
are shared and repository tasks rarely scale linearly. Failed or conflicting
worktrees are retained; successfully merged worktrees are removed.
Pushing is opt-in with `--push`.

Swarm mode invokes the installed provider CLI. Looptight neither supplies API
keys nor guarantees billing mode: Codex or Claude authentication determines
whether work consumes subscription allowance, credits, or another account.

## Safety

- Objective verifier output outranks model confidence.
- Only `pass` authorizes a commit.
- Timeout and launch errors never look like failing code.
- Headless execution requires explicit `--headless`.
- Concurrent tasks use atomic private claims.
- No force-push, hard reset, dependency installation, or fabricated work.
- Runtime state does not pollute project history.

See [the product specification](docs/SPEC.md), [current architecture](docs/architecture.md),
and [bounded self-improvement plan](docs/STATUS.md).

## Development

```bash
uv sync
uv run looptight verify --json
uv run ruff check
```

MIT
