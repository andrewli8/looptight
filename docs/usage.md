# Using looptight

Everyday use: install, a worked example, where tasks come from, and the local view.

## Quick start

```bash
uv tool install looptight        # or: uvx looptight ... , pipx install looptight
looptight init --integrate
```

`init` detects your test command and writes `.looptight.toml`. `--integrate` adds
one short, reviewable instruction block to `AGENTS.md` (Codex, OpenCode) or
`CLAUDE.md` (Claude Code) so the agent runs the loop without you re-prompting after
each task.

To let Claude Code discover looptight in every session, install its skill once:

```bash
looptight install-skill
```

This writes a small `SKILL.md` to `~/.claude/skills/looptight/`. Claude reads its
description and reaches for looptight when a task calls for a test-gated loop, with
no per-repo setup.

```toml
# .looptight.toml
verify = "pytest -q"        # exit 0 is the only passing verdict
tasks = ["docs/STATUS.md"]  # optional: files that list grounded work
direct_main = false         # require a worktree for unattended runs
```

Then, in your agent session, ask it to improve the repo. It will run `next`,
implement the task it gets back, run `verify`, and commit on a pass.

### Activate the coordinator (`migrate`)

`looptight doctor` will say `setup next: run looptight migrate`. That one-time
step activates the repo's coordinator, a private SQLite claim store that lets many
sessions and worktrees share one task queue safely:

```bash
looptight migrate
```

The loop also runs without it, using file-based claims, so a single solo session
works straight after `init`. The coordinator is the recommended setup once you run
more than one session against the repo; see
[architecture](architecture.md#repository-coordinator). Activation is one-way:
file claims fail closed afterward.

## A worked example

Say you have a tiny package with one loose end and one parked test. looptight scans
`src/` and `tests/` for signals:

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
2 candidate tasks (grouped by source priority; pick what to run):

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

A pass authorizes the commit. The agent commits the focused change and loops back to
`next`, which hands over the skipped test next. When both are done:

```bash
$ looptight next --json
{"command": "next", "schema_version": 1, "status": "no_work", "task": null}
```

`NO_WORK` ends the loop. Two real fixes landed, each one gated by your tests, and
nothing was invented to keep the session busy.

### Knowing when to stop (`verify --patience`)

When an agent keeps trying the same fix without making progress, it burns tokens
for nothing. Pass `--patience N` to `verify` and it tracks progress across calls:
after `N` iterations with no improvement, `verify --json` adds a `stall` object
whose `decision` is `stop_no_progress` (it improved, then plateaued) or `escalate`
(it never moved the needle), with the failures that never cleared. A `/loop`
wrapper or the host agent can watch that field and stop instead of grinding. A
passing verify resets the count. Without `--patience` the verifier is unchanged.

## How work is found

Tasks come from concrete repository signals, never from a model inventing audits to
stay busy:

| Source | What it reads |
|--------|---------------|
| `status-next` | the bounded `## Next` list in `docs/STATUS.md` |
| `task-file` | files you list under `tasks` in config |
| `skipped-test` | `@pytest.mark.skip` / `xfail` / `pytest.skip()`, plus JS/TS `it.skip` / `describe.skip` / `xit` / `xtest` |
| `todo` | real `TODO` / `FIXME` / `HACK` / `XXX` comments, not strings |
| `lint` | findings from your linter |

TODO and skipped-test discovery is polyglot: it scans Python and JS/TS (`.js`,
`.ts`, `.tsx`, and the rest of that family), including colocated `*.test.*` /
`*.spec.*` files and `__tests__/` directories, while ignoring markers inside strings
or comments and pruning vendored directories like `node_modules`.

Human-curated sources (`status-next`, `task-file`) rank above automated signals
(`lint`, `todo`), so deliberate intent gets claimed before incidental nits. A dirty
Git worktree returns a machine-readable error before any task is claimed.

### Writing your own tasks

To queue work yourself, add numbered items to a `## Next` section in `docs/STATUS.md`.
Each item needs two things, or looptight will not claim it: an `Evidence:` anchor that
points at a real file (so the task is grounded, not invented), and an `Acceptance:`
clause stating an observable outcome (so the verifier can tell when it is done).

```markdown
## Next

1. Reject negative amounts in the transfer endpoint. Evidence: src/api/transfer.py:42;
   Acceptance: a new test posts a negative amount and asserts a 400, and it passes.
```

An item whose `Evidence:` path does not resolve is dropped, so a fabricated reference
cannot enter the queue. This is the same bar the loop applies to tasks it generates.

To triage the queue, `looptight propose --source todo` (or `lint`, `skipped-test`,
`status-next`, `task-file`) shows only one signal type, and `looptight propose --eval`
scores the generated `## Next` batch on groundedness and diversity.

When the queue empties, looptight does not stop by default. `next` returns `no_work`
with a `generate_ideas` directive that asks the host session to add 1 to 6
evidence-backed tasks to `docs/STATUS.md`, then continue. looptight makes no model
call to do this. The agent that is already running and billed does the thinking, and
the directive's rule is strict: no evidence, no task, so the loop still terminates
when nothing real is left. Pass `--no-ideas` (or set `idea_generation = false`) to
stop on an empty queue instead.

Task claims live under Git's private common directory. They are shared across
worktrees, never show up as tracked files, and expire after 24 hours. Parallel
sessions should use separate worktrees.

## Local view

```bash
looptight status            # readiness plus a live worker panel, in the terminal
looptight status --watch    # the same panel, refreshing until you stop it
looptight ui                # http://127.0.0.1:8765 (read-only browser map)
```

`status` shows the swarm/daemon worker panel right in the CLI; `ui` is a
dependency-free, read-only browser map. Both read the same loopback-only state and
never open a public listener.

To see loop state in your Claude Code status bar, point `statusLine` at `looptight
statusline` (it reads Claude Code's status-line JSON on stdin and prints one line
like `looptight: 3 running, 1 merged`):

```json
{ "statusLine": { "type": "command", "command": "looptight statusline" } }
```
