"""Config load + init.

The entire mental model is one idea: ``verify`` (A3). Everything else has a
safe default and is just an override. Config lives in ``.looptight.toml`` at the
project root and is read with the stdlib ``tomllib`` (no write dependency — we
emit the file by hand so the comments survive).
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

CONFIG_NAME = ".looptight.toml"


class ConfigError(Exception):
    """A ``.looptight.toml`` exists but is invalid (bad TOML or a bad value).

    Carries a message naming the offending file so the CLI can fail fast with a
    clear, actionable line instead of a raw traceback.
    """

# Low, safe defaults (D1). budget_usd is a post-iteration spend threshold, not an
# unexceedable ceiling — one iteration can overshoot it; --budget raises it.
DEFAULT_MAX_ITERATIONS = 6
DEFAULT_BUDGET_USD = 1.00


@dataclass(frozen=True)
class Config:
    """Resolved run configuration."""

    verify: str | None = None
    agent: str | None = None  # None = auto-detect from PATH
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    budget_usd: float = DEFAULT_BUDGET_USD
    reflect: bool = True
    native: bool = False  # drive the agent's own loop (e.g. Claude /goal) where it has one
    hook: bool = False  # arm the Claude Code Stop-hook auto-loop in this repo
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
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{resolved} is not valid TOML: {exc}") from exc
    try:
        return Config(
            verify=data.get("verify"),
            agent=data.get("agent"),
            max_iterations=int(data.get("max_iterations", DEFAULT_MAX_ITERATIONS)),
            budget_usd=float(data.get("budget_usd", DEFAULT_BUDGET_USD)),
            reflect=_boolean(data, "reflect", True),
            native=_boolean(data, "native", False),
            hook=_boolean(data, "hook", False),
            patience=int(data.get("patience", 0)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{resolved} has an invalid value: {exc}") from exc


def _boolean(data: dict[str, object], field: str, default: bool) -> bool:
    value = data.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def render_config(config: Config) -> str:
    """Render a minimal, commented config file. The comments teach ``verify``."""
    verify = config.verify or "pytest -q"
    agent_line = (
        f"agent = {_toml_string(config.agent)}"
        if config.agent
        else '# agent = "claude"   # auto-detected if omitted'
    )
    return f"""# looptight config — the one concept that matters is `verify`.
# `verify` is the command that decides pass/fail. No verify, no loop.
# Exit code 0 means pass; anything else means keep going.
verify = {_toml_string(verify)}

# Everything below is optional and has a safe default.
{agent_line}
max_iterations = {config.max_iterations}   # hard cap; the loop stops here no matter what
budget_usd = {config.budget_usd}            # spend threshold; checked after each iteration, so one call can overshoot
reflect = {str(config.reflect).lower()}              # write a lesson to your agent's memory on failure
native = {str(config.native).lower()}               # drive the agent's own loop (e.g. Claude /goal) where it has one
hook = {str(config.hook).lower()}                 # arm the Claude Code Stop-hook auto-loop in this repo (needs `looptight install-hook`)
patience = {config.patience}                # stop early after N iterations with no measurable progress (0 = off)
"""


def _toml_string(value: str) -> str:
    """Encode a TOML basic string without pulling in a TOML writer."""
    return json.dumps(value, ensure_ascii=False)


def write_config(config: Config, directory: Path | None = None) -> Path:
    """Write ``.looptight.toml`` into ``directory`` (default cwd). Returns the path."""
    target = (directory or Path.cwd()) / CONFIG_NAME
    target.write_text(render_config(config), encoding="utf-8")
    return target
