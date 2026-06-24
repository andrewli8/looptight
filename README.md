# looptight

looptight keeps a coding agent honest with your tests. Point it at Claude Code,
Codex, or OpenCode and it runs one simple cycle: pick a real task, let the agent
do it, run your tests, and commit only if they pass. Then it goes again.

The point is that your tests decide, not the model. If `verify` (your test
command) does not pass, nothing gets committed. No verify, no loop.

looptight never starts another agent or calls a model of its own. It just drives
the session you already have open, so there is no extra setup and no API key to
manage.

Built with looptight: [asciimotion](https://github.com/andrewli8/asciimotion/tree/master),
an animated ASCII-art engine with a web app and a terminal CLI.

New here? Terms like verify, worktree, claim, swarm, and daemon are explained in
the [Glossary](#glossary).

## The loop

```text
   your agent session  (Claude Code / Codex / OpenCode)
   owns the model, auth, context, and code editing
        |
        v
   looptight next  ->  agent implements  ->  looptight verify
        ^                                          |
        |              commit if it passes         |
        +------------------ repeat <---------------+
                   stop when there is NO_WORK
```

`next` and `verify` make no model or network calls. They read the repository and
run your test command, nothing else. The installed package has no third-party runtime
dependency at all; it runs on the Python standard library.

## When to use it

- You pair with an agent and want every change gated by your real test suite,
  not by the model saying "looks good."
- You want the same loop across agents. Set it up once, then switch from Codex
  to Claude Code without re-teaching the workflow.
- You have a backlog of TODOs, skipped tests, or lint findings to burn down, in
  order, with a test gate on each fix.
- You want several agents working a repo at once, or the repo to keep improving
  itself while you are away.

If what you want is a second agent harness, looptight is not it. It is the
control plane the editors lack, not another editor.

## Quick start

```bash
uv tool install looptight
looptight init --integrate     # detect your tests, wire the loop into CLAUDE.md/AGENTS.md
looptight install-skill        # optional: let Claude Code discover looptight everywhere
```

Then ask your agent to improve the repo. It runs `next`, implements the task,
runs `verify`, and commits on a pass. Full walkthrough in [docs/usage.md](docs/usage.md).

## Commands

```bash
looptight init      # detect the test command, write config, optionally integrate
looptight next      # claim one grounded task, or return NO_WORK
looptight verify    # run the project's test command and report the verdict
looptight status    # show readiness and the next safe action, change nothing
looptight propose   # show the ranked task queue without claiming anything
looptight goal      # set or run a vision-driven build goal
looptight doctor    # show the detected agent, verify command, and adapters
```

Every command takes `--json` for scripting. `verify` exit codes: `0` pass, `1` a
real failing verdict, `2` a config or validator-execution error. The JSON result
tells `pass`, `fail`, `timeout`, and `error` apart, so a crashed test runner
never looks like failing code.

## What it can do

- **Backlog burndown** (the default loop above): claim grounded tasks and gate
  each on your tests. See [docs/usage.md](docs/usage.md).
- **Build from a vision** (`goal`): a self-driving 0-to-1 build, one verify-gated
  increment at a time. See [docs/goal.md](docs/goal.md).
- **Run unattended** (`run` / `swarm` / `daemon`): one headless agent, a parallel
  swarm, or a 24/7 supervisor. See [docs/unattended.md](docs/unattended.md).
- **Share a repo across sessions**: a repo-private coordinator hands out one queue
  safely. See [docs/architecture.md](docs/architecture.md).
- **Watch it work** (`status` / `status --watch` / `ui` / `statusline`): a live,
  loopback-only view of the loop. See [docs/usage.md](docs/usage.md#local-view).

## Safety

- Verifier output outranks model confidence. Only `pass` authorizes a commit.
- Timeout and launch errors never look like failing code.
- Headless execution needs an explicit `--headless`.
- Concurrent tasks use atomic private claims, so two agents never do the same work.
- No force-push, hard reset, dependency installation, or fabricated work.
- Optional `.looptight.toml` policy controls can fail closed on protected paths.
- Runtime state stays out of project history.

looptight supplies no API keys and makes no billing guarantee. Your provider's
authentication decides whether work spends a subscription, credits, or another
account.

## Glossary

- **verify**: the command that decides pass or fail, usually your test command.
  looptight runs it after each change and commits only when it passes.
- **worktree**: a separate working directory backed by the same Git repository, so
  parallel or unattended work stays isolated and never touches your open files.
- **headless**: running a coding agent as a child process instead of your
  interactive session. You opt in with `--headless`.
- **claim**: a private, atomic lock on a task so two sessions never do the same
  work. Claims live outside tracked history and expire after 24 hours.
- **swarm**: several headless workers doing independent tasks at once in isolated
  worktrees, with their verified results merged one at a time.
- **daemon**: a long-running supervisor that reruns a continuous swarm so the loop
  keeps going on its own.

## Learn more

- [Using looptight](docs/usage.md): setup, a worked example, where tasks come from.
- [Building toward a goal](docs/goal.md): the vision-driven `goal` mode.
- [Running unattended](docs/unattended.md): `run`, `swarm`, and the daemon.
- [Product specification](docs/SPEC.md): what looptight is and is not.
- [Architecture](docs/architecture.md): modules, roles, and the coordinator.

## Development

```bash
uv sync
uv run looptight verify --json
uv run ruff check
```

MIT
