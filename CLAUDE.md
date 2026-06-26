# looptight agent instructions

Keep the product provider-neutral, session-native, validation-first, and small.
The source of truth is `docs/SPEC.md`; the bounded running plan is
`docs/STATUS.md`. Do not add runtime dependencies or duplicate native agent
features without evidence that the portable protocol requires it.

## Task quality: avoid plausible busywork

The point of the loop is a continuous stream of high-quality, grounded tasks that
build the project 0 to 1 — not activity for its own sake. A task that contradicts
that purpose is worse than no task. Before generating or seeding one, pressure-test
it:

- Who consumes this, and can they already do it? A capability the agent in the loop
  already has (e.g. judging when it is stuck) does not need re-plumbing into that
  loop. Ask this first; it kills most bad ideas in one step.
- Wiring up or "completing" a feature is not a goal — a real consumer's loop working
  better is. Optimizing for symmetry or coverage is the tell that means and ends got
  inverted.
- Under pressure to keep producing, an adjacent extension of what you just built
  looks like work but is usually busywork. No evidence of a real gap means `NO_WORK`,
  a valid and honest outcome. Never fabricate to stay busy.
- Route a doubt to "is this correct?", not "do I need sign-off?" A correctness doubt
  mis-filed as a permissions question survives unexamined.

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
