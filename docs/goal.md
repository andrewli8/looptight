# Building toward a goal

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
