# Running looptight 24/7: the daemon

`looptight swarm --continuous` runs verified rounds and plans new grounded work
when the queue empties, but it is *bounded*: it returns when the backlog is
exhausted, when a usage limit persists, or on a fault. That is correct for a
one-shot invocation, and it is also why the loop does not run on its own. Nothing
restarts it.

`looptight daemon` is the supervisor that does. It runs the continuous swarm in a
cycle forever and, reading the structured outcome of each run, decides how long
to wait before the next one:

```text
   start
     |
     v
   run one continuous swarm cycle
     |
     +-- progress (a worker merged) ----> loop again immediately
     +-- idle (nothing to build) --------> wait --idle-sleep, then loop
     +-- fault (verify/push/crash) ------> capped exponential back-off, then loop
     |
   SIGTERM / Ctrl-C: finish this cycle, then stop
```

| Outcome | Meaning | Daemon reaction |
|---------|---------|-----------------|
| **progress** | a worker merged this cycle | loop again immediately to drain the backlog fast |
| **idle** | nothing grounded to build (including a waited-out usage limit) | poll again after `--idle-sleep` (default 600s) |
| **fault** | a real failure (verify, push, planner, crash) | exponential, capped back-off (`--fault-backoff` to `--fault-max-backoff`) |

Crashes inside a cycle are absorbed as faults, so a single bug never takes the
daemon down. It stops gracefully on `Ctrl-C` or `SIGTERM`, finishing the
in-flight cycle first.

## What the daemon is not

It is not a way around the two hard requirements for real 24/7 operation, which
no amount of code can conjure:

1. **A host that stays up.** Cloud cron routines (claude.ai) only fire scheduled,
   ephemeral sessions; they cannot hold a persistent process. The daemon needs a
   machine, VM, or container that runs continuously.
2. **A surviving agent authentication.** The daemon spawns your coding-agent CLI
   as child processes. That CLI must be installed and authenticated on the host
   (for example `ANTHROPIC_API_KEY`, or a persisted `claude login`).

## Sole writer to `main`

Run one writer against `main` at a time. If you adopt the daemon, disable any
cloud routines (improver, builder, reviewer) that also push to `main`. They would
race the daemon and waste each other's work. The daemon is itself verify-gated
(it never pushes a red tree) and never force-pushes, so it owns correctness on
its own.

## Running it

```bash
# Drain, plan, and build continuously, pushing verified commits to main:
looptight daemon --headless --agent claude --model opus --workers 4 --push

# Prove the loop locally first (verify-gated, no push):
looptight daemon --headless --max-cycles 3 --idle-sleep 5
```

Useful flags (see `looptight daemon --help` for all):

- `--idle-sleep N`: poll cadence when there is nothing to build (default 600s).
- `--fault-backoff N` / `--fault-max-backoff N`: fault back-off start and cap.
- `--max-cycles N`: stop after N cycles (0 = forever); handy for smoke tests.
- `--no-ideas`: when the queue empties, idle instead of generating grounded tasks.
- `--no-resume-on-limit`: treat a provider usage limit as a fault (default: wait it out).
- `--on-fault CMD`: run `CMD` when a cycle faults, for operator alerting. The
  daemon execs `CMD` with a JSON payload on stdin holding `cycle`, `reason`,
  `backoff_s`, and `last_error`. It is optional (default: no hook), and a failing
  or slow hook never stops the daemon (it is guarded and time-bounded).

The daemon prints one line per cycle (`cycle 7 → idle; next in 600s`), so the
journal shows exactly why it is or is not building at any moment. Idle is a
healthy state, not a stall.

## Deploy

- **systemd:** [`deploy/looptight-daemon.service`](../deploy/looptight-daemon.service).
  Put auth in `/etc/looptight/daemon.env` (chmod 600), then
  `systemctl enable --now looptight-daemon`, and follow with
  `journalctl -u looptight-daemon -f`.
- **Docker:** [`deploy/Dockerfile`](../deploy/Dockerfile). Add your agent CLI's
  install step, mount the target repo at `/workspace`, pass auth via `-e`, and run
  with `--restart unless-stopped`.
