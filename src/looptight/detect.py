"""Zero-config autodetection (A2).

Two jobs: find the coding agent on PATH, and infer the project's verify command
from the files in the repo. Both are best-effort and always overridable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Order = preference when several agents are installed.
KNOWN_AGENTS: tuple[str, ...] = ("claude", "codex", "opencode")


def detect_agent(preferred: str | None = None) -> str | None:
    """Return the name of an available agent, or None if none are on PATH.

    If ``preferred`` is given and available, it wins. Otherwise the first
    installed agent in ``KNOWN_AGENTS`` order is chosen.
    """
    if preferred:
        return preferred if shutil.which(preferred) else None
    for name in KNOWN_AGENTS:
        if shutil.which(name):
            return name
    return None


# (marker file, predicate, verify command). First match wins.
_VERIFY_RULES: tuple[tuple[str, str], ...] = (
    ("pyproject.toml", "pytest -q"),
    ("setup.cfg", "pytest -q"),
    ("pytest.ini", "pytest -q"),
    ("tox.ini", "pytest -q"),
    ("Cargo.toml", "cargo test"),
    ("go.mod", "go test ./..."),
)


def detect_verify(root: Path | None = None) -> str | None:
    """Infer a verify command from the project layout. None if nothing fits."""
    base = (root or Path.cwd()).resolve()

    package_json = base / "package.json"
    if package_json.is_file():
        # Only claim `npm test` if a test script actually exists.
        try:
            import json

            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
            if "test" in scripts:
                return "npm test"
        except (ValueError, OSError):
            pass

    for marker, command in _VERIFY_RULES:
        if (base / marker).is_file():
            return command

    makefile = base / "Makefile"
    if makefile.is_file():
        try:
            if any(
                line.startswith("test:") for line in makefile.read_text(encoding="utf-8").splitlines()
            ):
                return "make test"
        except OSError:
            pass

    return None
