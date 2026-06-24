# looptight

A test-gated work loop that runs inside the coding agent you already use. Point
it at Codex, Claude Code, or OpenCode and it drives the same cycle: pick a real
task, let the agent do it, run your tests, commit only if they pass, repeat.

looptight does not launch another agent or call a model. It coordinates the
session that is already open. The one idea you have to care about is `verify`:
the command that decides pass or fail. No verify, no loop.

New to terms like verify, worktree, headless, claim, swarm, or daemon? See the
[Glossary](#glossary).

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
run your test command, nothing else. The agent CLI owns authentication, model
choice, and usage limits. The installed package has no third-party runtime
dependency at all; it runs on the Python standard library.

## When to use it

- You pair with an agent and want every change gated by your real test suite,
  not by the model saying "looks good."
- You want the same loop across agents. Set it up once, then switch from Codex
  to Claude Code without re-teaching the workflow.
- You have a backlog of TODOs, skipped tests, or lint findings and want an agent
  to burn it down, in order, with a test gate on each fix.
- You want several agents working a repo at once in isolated worktrees, merged
  one at a time only when tests still pass.
- You want the repo to keep improving itself overnight or while you are away.

If what you want is a second agent harness, looptight is not it. It is the
control plane the editors lack, not another editor.

## Quick start

```bash
uvx looptight init --integrate
```

`init` detects your test command and writes `.looptight.toml`. `--integrate`
adds one short, reviewable instruction block to `AGENTS.md` (Codex, OpenCode) or
`CLAUDE.md` (Claude Code) so the agent runs the loop without you re-prompting
after each task.

```toml
# .looptight.toml
verify = "pytest -q"        # exit 0 is the only passing verdict
tasks = ["docs/STATUS.md"]  # optional: files that list grounded work
direct_main = false         # require a worktree for unattended runs
```

Then, in your agent session, ask it to improve the repo. It will run `next`,
implement the task it gets back, run `verify`, and commit on a pass.

## A worked example

Say you have a tiny package with one loose end and one parked test. looptight
scans `src/` and `tests/` for signals:

```text
calc/
  src/calc/core.py     # line 14:  # TODO: raise on divide by zero
  tests/test_core.py   # @pytest.mark.skip("decide behaviour first")
```

Set the test command and look at what looptight already sees:

```bash
$ looptight init
wrote .looptight.toml (verify = "pytest -q")

$ looptight propose
2 candidate task(s) (grouped by source priority; pick what to run):

todo
  1. raise on divide by zero  src/calc/core.py:14

skipped-test
  2. un-skip / fix skipped test in test_core.py  tests/test_core.py:8
```

Claim the first task. The agent reads this, not you:

```bash
$ looptight next --json
{
  "command": "next",
  "schema_version": 1,
  "status": "task",
  "task": {
    "id": "3f9a1c0b7d22",
    "source": "todo",
    "location": "src/calc/core.py:14",
    "goal": "raise on divide by zero",
    "evidence": "src/calc/core.py:14",
    "acceptance": "Remove the marker at src/calc/core.py:14 and pass project verification."
  }
}
```

The agent edits `src/calc/core.py`. Now the gate runs:

```bash
$ looptight verify --json
{"command": "verify", "status": "pass", "exit_code": 0, "duration_ms": 812.4, ...}
```

A pass authorizes the commit. The agent commits the focused change and loops
back to `next`, which hands over the skipped test next. When both are done:

```bash
$ looptight next --json
{"command": "next", "schema_version": 1, "status": "no_work", "task": null}
```

`NO_WORK` ends the loop. Two real fixes landed, each one gated by your tests,
and nothing was invented to keep the session busy.

## Commands

```bash
looptight init      # detect the test command, write config, optionally integrate
looptight next      # claim one grounded task, or return NO_WORK
looptight verify    # run the project's test command and report the verdict
looptight status    # show readiness and the next safe action, change nothing
looptight propose   # show the ranked task queue without claiming anything
looptight goal      # set or run a vision-driven build goal (see below)
looptight doctor    # show the detected agent, verify command, and adapters
```

Every command takes `--json` for scripting. `verify` exit codes: `0` pass,
`1` a real failing verdict, `2` a config or validator-execution error. The JSON
result tells `pass`, `fail`, `timeout`, and `error` apart, so a crashed test
runner never looks like failing code.

## Building toward a goal

`next` is evidence-first: it refines an existing codebase from real repo signals.
`goal` is the other direction. Give it a vision and it drives the loop forward, one
verify-gated increment at a time, generating the next step from the vision and the
current state. It is the looptight take on a self-driving build: a real exit-code
gate instead of a model judging the transcript, and it works in any agent session.

```bash
looptight goal "a CLI todo app with add, list, and done, plus pytest coverage"
```

The host session then loops: `looptight goal next` hands it one increment to build,
`looptight verify` gates the commit, repeat. On an empty repo the first increment
scaffolds the project and a test command, so the gate is real within a step or two.

- `--done "<cmd>"` ends the goal when that command exits `0` (a real, deterministic
  finish, not a model's guess).
- `--max-iterations N` is a soft backstop: the loop stops after `N` increments
  (`0` = unlimited).
- `--continuous` declares a hands-off run until usage is spent and prints the driver
  recipe for your agent.

looptight cannot see your provider usage, so "run until usage is spent" is owned by
the driver and the session limit, not looptight. On Claude Code, drive it hands-off
with the native loop:

```bash
looptight goal "<vision>" --continuous
/loop until: looptight goal check
```

`goal next` and `verify` make no model or network calls; the already-running session
does the building. `looptight goal status` shows the active goal; `looptight goal
clear` ends it.

## How work is found

Tasks come from concrete repository signals, never from a model inventing audits
to stay busy:

| Source | What it reads |
|--------|---------------|
| `status-next` | the bounded `## Next` list in `docs/STATUS.md` |
| `task-file` | files you list under `tasks` in config |
| `skipped-test` | `@pytest.mark.skip` / `xfail` / `pytest.skip()`, plus JS/TS `it.skip` / `describe.skip` / `xit` |
| `todo` | real `TODO` / `FIXME` / `HACK` / `XXX` comments, not strings |
| `lint` | findings from your linter |

TODO and skipped-test discovery is polyglot: it scans Python and JS/TS (`.js`,
`.ts`, `.tsx`, and the rest of that family), including colocated `*.test.*` /
`*.spec.*` files and `__tests__/` directories, while ignoring markers inside
strings or comments and pruning vendored directories like `node_modules`.

Human-curated sources (`status-next`, `task-file`) rank above automated signals
(`lint`, `todo`), so deliberate intent gets claimed before incidental nits. A
dirty Git worktree returns a machine-readable error before any task is claimed.

When the queue empties, looptight does not stop by default. `next` returns
`no_work` with a `generate_ideas` directive that asks the host session to add 1
to 6 evidence-backed tasks to `docs/STATUS.md`, then continue. looptight makes no
model call to do this. The agent that is already running and billed does the
thinking, and the directive's rule is strict: no evidence, no task, so the loop
still terminates when nothing real is left. Pass `--no-ideas` (or set
`idea_generation = false`) to stop on an empty queue instead.

Task claims live under Git's private common directory. They are shared across
worktrees, never show up as tracked files, and expire after 24 hours. Parallel
sessions should use separate worktrees.

## Running it unattended

The default loop runs inside your interactive session. Three explicit modes run
without you sitting there.

**One headless agent.** `run` launches your provider CLI and applies the same
verifier after each iteration:

```bash
looptight run --headless "fix the failing tests"
```

**A swarm.** A deterministic manager claims one task per worker, gives each its
own worktree and branch, runs them at once, and merges successful branches one
at a time, re-running the verifier before every merge:

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

**A daemon.** `swarm --continuous` still returns when the backlog is empty.
`looptight daemon` is the supervisor that reruns it forever: it loops at once
after merged progress, polls after a back-off when idle, and backs off on faults.

```bash
looptight daemon --headless --agent claude --model opus --workers 4 --push
```

It needs a host that stays up and an authenticated agent, and should be the only
writer to `main`. See [`docs/daemon.md`](docs/daemon.md) for the systemd unit,
the container image, and every flag.

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
coordinator-owned worktree, and crash recovery is idempotent. Coordination is
local to one machine and filesystem. Turn it on with:

```bash
looptight migrate    # writes the coordinator marker; --json for machine output
```

`migrate` refuses (exit 2) while any legacy file claim is still live, errors
outside Git, and is idempotent. See [`docs/architecture.md`](docs/architecture.md)
for the model.

## Local view

```bash
looptight status            # readiness plus a live worker panel, in the terminal
looptight status --watch    # the same panel, refreshing until you stop it
looptight ui                # http://127.0.0.1:8765 (read-only browser map)
```

`status` shows the swarm/daemon worker panel right in the CLI; `ui` is a
dependency-free, read-only browser map. Both read the same loopback-only state and
never open a public listener.

To see loop state in your Claude Code status bar, point `statusLine` at
`looptight statusline` (it reads Claude Code's status-line JSON on stdin and prints
one line like `looptight: 3 running · 1 merged`):

```json
{ "statusLine": { "type": "command", "command": "looptight statusline" } }
```

## Safety

- Verifier output outranks model confidence. Only `pass` authorizes a commit.
- Timeout and launch errors never look like failing code.
- Headless execution needs an explicit `--headless`.
- Concurrent tasks use atomic private claims, so two agents never do the same
  work.
- No force-push, hard reset, dependency installation, or fabricated work.
- Optional `.looptight.toml` policy controls can fail closed on protected paths.
- Runtime state stays out of project history.

Swarm and daemon modes invoke your provider CLI. looptight supplies no API keys
and makes no billing guarantee: your provider's authentication decides whether
work spends a subscription, credits, or another account.

## Glossary

- **verify**: the command that decides pass or fail, usually your test command.
  looptight runs it after each change and commits only when it passes. No verify, no loop.
- **worktree**: a separate working directory backed by the same Git repository, so
  parallel or unattended work stays isolated and never touches your open files.
- **headless**: running a coding agent as a child process instead of your
  interactive session. You opt in with `--headless`; the default loop stays in the
  session you already have open.
- **claim**: a private, atomic lock on a task so two sessions never do the same
  work. Claims live outside tracked history and expire after 24 hours.
- **swarm**: several headless workers doing independent tasks at once in isolated
  worktrees, with their verified results merged one at a time.
- **daemon**: a long-running supervisor that reruns a continuous swarm so the loop
  keeps going on its own, backing off when idle and recovering from faults.

## Learn more

- [Product specification](docs/SPEC.md): what looptight is and is not.
- [Architecture](docs/architecture.md): modules, roles, and the coordinator.
- [Running 24/7](docs/daemon.md): the daemon and how to deploy it.
- [`docs/STATUS.md`](docs/STATUS.md): the bounded self-improvement plan.

## Development

```bash
uv sync
uv run looptight verify --json
uv run ruff check
```

MIT
