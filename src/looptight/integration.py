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
5. Stop successfully on `no_work`. Stop safely on validator `timeout` or `error`.

Do not run `looptight run` or `looptight improve` from this workflow: those
launch child agents. `next` and `verify` make no model or API calls and use this
session's existing provider subscription.
{END}
"""


def install_session_instructions(root: Path) -> list[Path]:
    """Install one idempotent managed block for all three supported CLIs."""
    changed: list[Path] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = root / name
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if START in current and END in current:
            before, remainder = current.split(START, 1)
            _, after = remainder.split(END, 1)
            prefix = before.rstrip()
            updated = (prefix + "\n\n" if prefix else "") + SESSION_LOOP + after.lstrip("\n")
        else:
            updated = current.rstrip() + ("\n\n" if current.strip() else "") + SESSION_LOOP
        if updated != current:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed
