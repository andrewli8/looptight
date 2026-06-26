# Running it unattended

The default loop runs inside your interactive session. Three explicit modes run
without you sitting there, and a coordinator lets many sessions share one repo.

## One headless agent

`run` launches your provider CLI and applies the same verifier after each iteration:

```bash
looptight run --headless "fix the failing tests"
```

### Stopping early when stuck (`--patience`)

By default `run` keeps going to its iteration cap. Pass `--patience N` to stop
early when the verifier stops making progress for `N` iterations in a row:

```bash
looptight run --headless "fix the failing tests" --patience 3
```

This is off by default (`--patience 0`). When it triggers, the run summary
explains why instead of just giving up: the failures that never cleared across the
attempts, plus the progress trajectory. It tells apart "made progress, then
stalled" (cut losses) from "never moved the needle" (worth a human look). The same
report is in `looptight run --json` as an additive `escalation` object.

## A swarm

A deterministic manager claims one task per worker, gives each its own worktree and
branch, runs them at once, and merges successful branches one at a time, re-running
the verifier before every merge:

```bash
looptight swarm --headless --agent codex --workers 4
```

One invocation drains one snapshot of the queue and exits. Failed or conflicting
worktrees are kept for inspection (`git worktree list`); merged ones are removed.
Pushing is opt-in with `--push`. Add `--continuous` to plan new work and run more
rounds, and `--resume-on-limit` to wait out a provider usage limit and resume
instead of stopping.

```text
grounded queue
   |--> worktree A --> worker --> verify --+
   |--> worktree B --> worker --> verify --+--> merge one at a time
   |--> worktree C --> worker --> verify --+    (re-verify before each)
```

## A daemon

`swarm --continuous` still returns when the backlog is empty. `looptight daemon` is
the supervisor that reruns it forever: it loops at once after merged progress, polls
after a back-off when idle, and backs off on faults.

```bash
looptight daemon --headless --agent claude --model opus --workers 4 --push
```

It needs a host that stays up and an authenticated agent, and should be the only
writer to `main`. See [daemon.md](daemon.md) for the systemd unit, the container
image, and every flag.

To survive a closed laptop, keep the process alive and the machine awake:

```bash
tmux new -s looptight
caffeinate -s looptight daemon --headless --agent claude --workers 4 --push
# detach with Ctrl-b d
```

## Multiple sessions on one repository

A repository-private SQLite coordinator lets many local sessions share one repo
safely:

```text
many sessions --> shared queue --> isolated worktrees --> verify --> merge one at a time
```

Task leases are fenced, integration serializes behind a repository lock in a
coordinator-owned worktree, and crash recovery is idempotent. Coordination is local
to one machine and filesystem. Turn it on with:

```bash
looptight migrate    # writes the coordinator marker; --json for machine output
```

`migrate` refuses (exit 2) while any legacy file claim is still live, errors outside
Git, and is idempotent. See [architecture.md](architecture.md) for the model.
