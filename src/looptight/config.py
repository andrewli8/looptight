"""Config load + init.

The entire mental model is one idea: ``verify`` (A3). Everything else has a
safe default and is just an override. Config lives in ``.looptight.toml`` at the
project root and is read with the stdlib ``tomllib`` (no write dependency — we
emit the file by hand so the comments survive).
"""

from __future__ import annotations

import difflib
import json
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from .fsutil import atomic_write_text

CONFIG_NAME = ".looptight.toml"


class ConfigError(Exception):
    """A ``.looptight.toml`` exists but is invalid (bad TOML or a bad value).

    Carries a message naming the offending file so the CLI can fail fast with a
    clear, actionable line instead of a raw traceback.
    """

DEFAULT_MAX_ITERATIONS = 6

#: The example verify command written into a fresh config when none is detected.
#: Shared so the rendered file and `init`'s message name the same default.
DEFAULT_VERIFY = "pytest -q"


@dataclass(frozen=True)
class Config:
    """Resolved run configuration."""

    verify: str | None = None
    tasks: tuple[str, ...] = ()
    direct_main: bool = False  # explicitly permit unattended execution in the primary worktree
    idea_generation: bool = True  # generate grounded tasks when the queue is empty (off: --no-ideas)
    continue_through_backlog: bool = False  # Stop hook keeps the session going while grounded tasks remain
    protected_paths: tuple[str, ...] = ()
    no_direct_push: bool = False
    max_changed_files: int | None = None
    allowed_verify_commands: tuple[str, ...] = ()

    # Runtime-only controls retained for the explicit headless commands. These
    # are not part of the project configuration file contract.
    agent: str | None = None  # None = auto-detect from PATH
    model: str | None = None  # provider model for spawned sessions (e.g. "opus"); None = CLI default
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    native: bool = False  # drive the agent's own loop (e.g. Claude /goal) where it has one
    patience: int = 0  # stop early after N iterations of no measurable progress (0 = off)

    def merged(self, **overrides: object) -> "Config":
        """Return a new Config with any non-None overrides applied (CLI > file)."""
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **clean) if clean else self


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` looking for ``.looptight.toml``."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> Config:
    """Load config from ``path`` (or the nearest one found). Missing file = defaults."""
    resolved = path or find_config()
    if resolved is None or not resolved.is_file():
        return Config()
    try:
        # ``utf-8-sig`` strips a leading BOM (common from Windows editors) that
        # tomllib would otherwise reject; it is a no-op for plain UTF-8.
        data = tomllib.loads(resolved.read_text(encoding="utf-8-sig"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{resolved} is not valid TOML: {exc}") from exc
    _reject_misplaced_keys(resolved, data)
    _reject_typo_keys(resolved, data)
    try:
        return Config(
            verify=_optional_string(data, "verify"),
            tasks=_string_list(data, "tasks"),
            direct_main=_boolean(data, "direct_main", False),
            idea_generation=_boolean(data, "idea_generation", True),
            continue_through_backlog=_boolean(data, "continue_through_backlog", False),
            protected_paths=_string_list(data, "protected_paths"),
            no_direct_push=_boolean(data, "no_direct_push", False),
            max_changed_files=_optional_int(data, "max_changed_files"),
            allowed_verify_commands=_string_list(data, "allowed_verify_commands"),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{resolved} has an invalid value: {exc}") from exc


#: The config schema is flat (top-level keys only). These are every recognized key, used to
#: catch keys mistakenly nested under a TOML table like ``[policy]`` — where they would be
#: silently dropped, including safety-relevant ones (protected_paths, max_changed_files).
_KNOWN_FIELDS = frozenset(
    {
        "verify",
        "tasks",
        "direct_main",
        "idea_generation",
        "continue_through_backlog",
        "protected_paths",
        "no_direct_push",
        "max_changed_files",
        "allowed_verify_commands",
    }
)


def _reject_typo_keys(resolved: Path, data: dict[str, object]) -> None:
    """Fail fast on a top-level scalar key that is a near-miss of a recognized field.

    A typo like ``verfy = "true"`` for ``verify`` would otherwise be silently dropped, leaving
    the user believing they set a value that never took effect — the same footgun as a misplaced
    key. A genuinely-unrelated unknown key (not close to any field) is left alone so a newer
    config key does not break an older binary (forward-compatible).
    """
    for key, value in data.items():
        if key in _KNOWN_FIELDS or isinstance(value, dict):
            continue  # recognized, or a table (handled by _reject_misplaced_keys)
        close = difflib.get_close_matches(key, _KNOWN_FIELDS, n=1, cutoff=0.75)
        if close:
            raise ConfigError(
                f"{resolved}: unknown config key '{key}' — did you mean '{close[0]}'?"
            )


def _reject_misplaced_keys(resolved: Path, data: dict[str, object]) -> None:
    """Fail fast when recognized config keys are nested under a TOML table.

    The schema is flat, so ``[policy]\\nmax_changed_files = 3`` is never read. Silently
    dropping a safety setting the user believes they set is a footgun; an unknown table with
    no recognized keys is left alone (forward-compatible).
    """
    for table, value in data.items():
        if not isinstance(value, dict):
            continue
        misplaced = _KNOWN_FIELDS & value.keys()
        if misplaced:
            keys = ", ".join(sorted(misplaced))
            raise ConfigError(
                f"{resolved}: config keys are top-level, not under a [{table}] table; "
                f"move {keys} out of [{table}]"
            )


def _boolean(data: dict[str, object], field: str, default: bool) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _optional_string(data: dict[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _optional_int(data: dict[str, object], field: str) -> int | None:
    value = data.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _string_list(data: dict[str, object], field: str) -> tuple[str, ...]:
    value = data.get(field, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of nonempty strings")
    return tuple(value)


def render_config(config: Config) -> str:
    """Render a minimal, commented config file. The comments teach ``verify``."""
    verify = config.verify or DEFAULT_VERIFY
    tasks = ", ".join(_toml_string(task) for task in config.tasks)
    return f"""# looptight config — the one concept that matters is `verify`.
# `verify` is the command that decides pass/fail. No verify, no loop.
# Exit code 0 means pass; anything else means keep going.
verify = {_toml_string(verify)}

# Optional grounded task files and unattended primary-worktree permission.
tasks = [{tasks}]
direct_main = {str(config.direct_main).lower()}

# Generate grounded tasks when the queue empties (set false, or pass --no-ideas).
idea_generation = {str(config.idea_generation).lower()}

# Let the Stop hook keep the session going while grounded tasks remain (honest stop when
# none do). Opt-in; the hook otherwise just runs verify-until-green.
continue_through_backlog = {str(config.continue_through_backlog).lower()}

# Optional policy controls. Empty values are disabled.
protected_paths = []
no_direct_push = false
allowed_verify_commands = []
"""


def _toml_string(value: str) -> str:
    """Encode a TOML basic string without pulling in a TOML writer."""
    return json.dumps(value, ensure_ascii=False)


def write_config(config: Config, directory: Path | None = None) -> Path:
    """Write ``.looptight.toml`` into ``directory`` (default cwd). Returns the path.

    Atomic, like the other user-file writers (goal, ui, settings): an interrupted
    write must not leave a partial config behind — `init` refuses to overwrite an
    existing file, so a half-written one would otherwise strand the user.
    """
    target = (directory or Path.cwd()) / CONFIG_NAME
    atomic_write_text(target, render_config(config))
    return target
