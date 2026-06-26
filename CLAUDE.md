# looptight agent instructions

The inviolable principles are `docs/SPEC.md` § Principles. Read them. Never trade
one away for a feature or to keep a loop busy. In short: a portable control plane
(not a second agent), validation as the only authority, no model calls in the
session-native path, grounded tasks only, honest signals, safe by default, small
and stdlib-only.

The source of truth is `docs/SPEC.md`. The bounded plan is `docs/STATUS.md`.

## Task quality: avoid plausible busywork

The loop generates grounded tasks that build the project 0 to 1, not activity. A
task that contradicts that is worse than no task. Pressure-test every idea before
seeding it:

- Who consumes this, and can they already do it? A capability the agent already has
  in the loop (knowing when it is stuck) needs no re-plumbing. Ask first; it kills
  most bad ideas in one step.
- Completing or wiring up a feature is not a goal. A real consumer's loop working
  better is. Optimizing for symmetry or coverage is the tell that means and ends got
  inverted.
- Under pressure to produce, an adjacent extension of what you just built looks like
  work but is usually busywork. No real gap means `NO_WORK`. Never fabricate.
- Route a doubt to "is this correct?", not "do I need sign-off?" A correctness doubt
  filed as a permissions question survives unexamined.

<!-- looptight:session-loop:start -->
## Looptight session loop

When asked to improve this repository autonomously:

1. Read `docs/STATUS.md`, then run `looptight next --json`.
2. If the status is `task`, implement only that grounded task in this session.
3. Run `looptight verify --json`; only `pass` authorizes a commit.
4. Review the diff, update `docs/STATUS.md` by replacement rather than logging,
   commit the coherent change, push when authorized, and repeat from step 1.
5. On `no_work` carrying a `generate_ideas` directive, add 1-6 grounded tasks
   (each with `Evidence: relative/path[:line]` and an observable `Acceptance:`)
   to the `## Next` section of `docs/STATUS.md` per that directive, then repeat
   from step 1. Stop successfully when no evidence-backed improvement exists,
   when idea generation is disabled (`--no-ideas` or `idea_generation = false`),
   or on a `next` error or validator `timeout` / `error`.

Do not run `looptight run` or `looptight improve` from this workflow: those
launch child agents. `next` and `verify` make no model or API calls and use this
already-running session; the provider controls authentication and billing.
<!-- looptight:session-loop:end -->
