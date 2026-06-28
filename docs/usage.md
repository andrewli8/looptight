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

### Activate the coordinator (`migrate`) — optional

A solo loop is ready without this: `looptight doctor` reports `setup: ready` and
only hints at `migrate`. In fact `next` already claims through the repo's
coordinator — a private SQLite claim store — in **any** Git repository, whether or
not you have run `migrate`, which is why `doctor`/`status` report the coordinator
as active for a plain repo. So a single solo session works straight after `init`
with no extra step.

What `migrate` does is **fence the legacy file-claim mechanism**, not switch the
store on:

```bash
looptight migrate
```

Run it when an older checkout may still hold live file-based claims and you want
them retired before the coordinator is the sole authority. It refuses while any
legacy file claim is still live, then writes a marker after which legacy file
claims fail closed; it is idempotent and errors outside Git. The coordinator
itself is already the claim store for every session and worktree of the repo; see
[architecture](architecture.md#repository-coordinator).

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
| `skipped-test` | pytest (`@pytest.mark.skip`/`xfail`/`skipif`, imperative `pytest.skip()`/`pytest.xfail()`, and parametrize `marks=`), stdlib `unittest`, plus JS/TS `it.skip` / `describe.skip` / `.fixme` / `.failing` / `xit` (Jest, Vitest, Mocha, Playwright, Cypress) |
| `todo` | real `TODO` / `FIXME` / `HACK` / `XXX` comments — including `TODO(author):` / `[ticket]:` attribution and the JSDoc `@todo` tag — not strings |
| `lint` | findings from your linter |

TODO and skipped-test discovery is polyglot and layout-agnostic. For Python it
scans the whole project, so a `src/` layout, a flat package (`mypackage/`), or
top-level modules (`app.py`) all work. For JS/TS it scans the whole
`.js`/`.jsx`/`.ts`/`.tsx`/`.mjs`/`.cjs`/`.mts`/`.cts` family for TODOs, and finds
skipped tests under `src/`, `tests/`, `test/` (Mocha), and `spec/` (Jasmine) plus
colocated `*.test.*` / `*.spec.*` / `*.cy.*` (Cypress) files and `__tests__/`
directories. Either way it ignores markers inside strings or comments, respects
`.gitignore`, and prunes vendored and cache directories (`node_modules`, `.venv`,
`build`, `__pycache__`, and the rest).

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
