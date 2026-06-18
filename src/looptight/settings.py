"""Install/uninstall the looptight Stop hook in a Claude Code settings.json.

Idempotent JSON surgery. We add exactly one ``Stop`` hook entry whose command is
``looptight hook`` and recognize our own entry by that command string, so
re-running install is a no-op and uninstall removes only what we added. We never
clobber a settings file we can't parse: a malformed file raises rather than being
overwritten.
"""

from __future__ import annotations

import json
from pathlib import Path

HOOK_COMMAND = "looptight hook"
HOOK_TIMEOUT_S = 120


def user_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def project_settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON; refusing to edit it ({exc})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object; refusing to edit it")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _hook_entry() -> dict:
    return {
        "matcher": "*",
        "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": HOOK_TIMEOUT_S}],
    }


def _is_ours(entry: dict) -> bool:
    return any(
        isinstance(h, dict) and h.get("command") == HOOK_COMMAND
        for h in entry.get("hooks", [])
    )


def install(path: Path) -> bool:
    """Add the Stop hook to ``path``. Returns True if added, False if already there.

    Builds a new settings object rather than mutating shared state (the loaded
    dict is local to this call, but we keep the merge explicit and copy-based).
    """
    data = _load(path)
    raw_hooks = data.get("hooks", {})
    if not isinstance(raw_hooks, dict):
        raise ValueError(f"{path}: hooks is not an object; refusing to edit")
    hooks = dict(raw_hooks)
    stop = list(hooks.get("Stop", []))
    if any(_is_ours(entry) for entry in stop if isinstance(entry, dict)):
        return False
    stop.append(_hook_entry())
    hooks["Stop"] = stop
    _write(path, {**data, "hooks": hooks})
    return True


def uninstall(path: Path) -> int:
    """Remove looptight Stop hook entries. Returns how many were removed."""
    if not path.is_file():
        return 0
    data = _load(path)
    raw_hooks = data.get("hooks", {})
    if not isinstance(raw_hooks, dict):
        raise ValueError(f"{path}: hooks is not an object; refusing to edit")
    hooks = dict(raw_hooks)
    stop = list(hooks.get("Stop", []))
    kept = [entry for entry in stop if not (isinstance(entry, dict) and _is_ours(entry))]
    removed = len(stop) - len(kept)
    if removed:
        hooks["Stop"] = kept
        _write(path, {**data, "hooks": hooks})
    return removed
