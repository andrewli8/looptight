"""Small, provider-neutral project instructions for native agent sessions."""

from __future__ import annotations

from pathlib import Path

START = "<!-- looptight:session-loop:start -->"
END = "<!-- looptight:session-loop:end -->"

SESSION_LOOP = f"""{START}
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
{END}
"""


def install_session_instructions(root: Path) -> list[Path]:
    """Install one idempotent managed block for all three supported CLIs."""
    changed: list[Path] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if START in current:
            before, remainder = current.split(START, 1)
            after = remainder.split(END, 1)[1] if END in remainder else ""
            prefix = before.rstrip()
            updated = (prefix + "\n\n" if prefix else "") + SESSION_LOOP + after.lstrip("\n")
        else:
            updated = current.rstrip() + ("\n\n" if current.strip() else "") + SESSION_LOOP
        if updated != current:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed
