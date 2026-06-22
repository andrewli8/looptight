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
`docs/STATUS.md`, source TODOs, skipped tests, and lint findings; human-curated
sources (`docs/STATUS.md` Next, configured task files) rank above automated lint
and TODO signals. A dirty Git worktree returns a machine-readable error before
proposal discovery or claim mutation.

By default an empty queue does not end the loop: `next` returns `no_work` carrying
a `generate_ideas` directive, and the session is instructed to add 1-6
evidence-backed tasks to `docs/STATUS.md` Next and continue. looptight makes no
model call to do this — the host session generates; only grounded, evidence-backed
tasks are added, so the loop still terminates when nothing real remains. Pass
`looptight next --no-ideas` (or set `idea_generation = false` in `.looptight.toml`)
to restore stop-on-empty. The continuous swarm honors the same `--no-ideas`.

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
looptight swarm --headless --agent codex --workers 4 --worker-timeout 3600 --push
# or: --agent claude
```

The deterministic manager claims up to one grounded task per worker, creates an
isolated Git worktree and branch for each, runs workers concurrently, and merges
successful branches one at a time only when the project verifier still passes.
The hard limit is 50 workers; start with a small value because provider limits
are shared and repository tasks rarely scale linearly. Failed, conflicting, or
timed-out worktrees are retained; a timeout terminates the provider process tree.
Successfully merged worktrees are removed.
Pushing is opt-in with `--push`.

One invocation drains one snapshot of the grounded queue and then exits. Run it
again to consume tasks exposed by merged changes; `NO_WORK` means no provider
process was launched. Worker branches use `looptight/swarm/...`. On failure,
inspect retained workers with `git worktree list`; successful branches remain as
an audit/recovery point even after their worktrees are removed.

For automatic planning and repeated rounds, opt in explicitly:

```bash
looptight swarm --headless --continuous --agent codex --workers 4 --push
# optional safety cap: --max-rounds 10 (0 means uncapped)
```

Continuous mode drains grounded tasks, then runs the selected provider CLI once
as a planning manager in an isolated worktree. A plan is merged only when it
changes `docs/STATUS.md`, contains 1–6 tasks with existing-file `Evidence:`
references and observable `Acceptance:` clauses, and passes verification in the
planner worktree and again during integration. It then starts another swarm
round. It stops on an evidence-backed `NO_WORK`, provider or verification
failure, the optional round cap, or interruption. Invalid planner worktrees are
retained for inspection. Task fingerprints remain stable when the same task is
found through another configured source, and interruption terminates active
provider process trees before returning control.

### Unattended through usage limits

By default a usage/rate limit stops the run. Opt in to wait it out and resume —
the keystone for self-improving overnight or while you are away:

```bash
looptight swarm --headless --continuous --resume-on-limit --agent codex --workers 4
# tuning: --limit-backoff-seconds 30   --limit-max-wait-seconds 3600
```

Looptight never tracks tokens; it only reacts to a usage/rate limit the provider
reports in its own output, then sleeps (preferring the provider's named reset,
otherwise exponential back-off capped by `--limit-max-wait-seconds`) and resumes.
A long reset is handled by re-polling, not one unbounded wait. The same flags
work on the single-agent loop (`looptight run --headless --resume-on-limit ...`),
which is the path a scheduled/cloud trigger drives.

To survive a closed laptop, keep the process alive and the machine awake:

```bash
tmux new -s looptight
caffeinate -s looptight swarm --headless --continuous --resume-on-limit --agent codex
# detach with Ctrl-b d; `caffeinate -s` keeps macOS awake while plugged in
```

The orchestrator (`swarm`/`run`) is deterministic and spends no allowance; only
the workers it spawns — and the occasional planner — invoke the provider. See
`docs/architecture.md` for the full role breakdown.

### Multiple sessions on one repository

A repository-private SQLite coordinator lets many local sessions share one repo:
shared task queue → isolated worktrees → verify → one-at-a-time Git integration.
Task leases are fenced, integration serializes behind a repository advisory lock in
a coordinator-owned worktree, and crash recovery is idempotent (integration trailers;
fetch-before-push publication). Coordination is local to one machine and filesystem.
`next`/`status` JSON keys are unchanged — coordinator counts appear additively under
a `coordinator` block on `status`. See `docs/architecture.md` for the model.

Activate the coordinator for a repository with:

```bash
looptight migrate    # writes the coordinator marker; --json for machine output
```

`migrate` refuses (exit 2) while any legacy file claim is still live, errors outside
Git, and is idempotent. After activation the coordinator owns task ownership and
legacy file claims fail closed.

Swarm mode invokes the installed provider CLI. Looptight neither supplies API
keys nor guarantees billing mode: provider authentication determines whether
work consumes subscription allowance, credits, or another account.

### Local orchestration view

```bash
looptight ui                 # http://127.0.0.1:8765
looptight ui --port 9123
```

The dependency-free, read-only signal map polls Git-private swarm state and
shows the manager, grounded tasks, workers, arrows, and live outcomes. It binds
only to loopback and sends restrictive browser headers. Provider-native Codex,
Claude Code, or OpenCode surfaces remain the manager interface; Looptight never
opens a public listener itself.

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
