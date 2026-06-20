<!-- looptight:session-loop:start -->
## Looptight session loop

When asked to improve this repository autonomously:

1. Read `docs/STATUS.md`, then run `looptight next --json`.
2. If the status is `task`, implement only that grounded task in this session.
3. Run `looptight verify --json`; only `pass` authorizes a commit.
4. Review the diff, update `docs/STATUS.md` by replacement rather than logging,
   commit the coherent change, push when authorized, and repeat from step 1.
5. Stop successfully on `no_work`. Stop safely on validator `timeout` or `error`.

Do not run `looptight run` or `looptight improve` from this workflow: those
launch child agents. `next` and `verify` make no model or API calls and use this
session's existing provider subscription.
<!-- looptight:session-loop:end -->
