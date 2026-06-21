"""Zero-config autodetection (A2).

Two jobs: find the coding agent on PATH, and infer the project's verify command
from the files in the repo. Both are best-effort and always overridable.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# Order = preference when several agents are installed.
KNOWN_AGENTS: tuple[str, ...] = ("claude", "codex", "opencode")

# A Make `test` rule: "test" then optional spaces and a colon, but NOT an
# assignment (`test:=` / `test::=` / `test ::=`). The lookahead rejects an "="
# right after the colon(s) so a variable named `test` isn't read as a target.
_MAKE_TEST_TARGET = re.compile(r"test\s*:(?!:?=)")


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

            manifest = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = manifest.get("scripts", {}) if isinstance(manifest, dict) else {}
            if not isinstance(scripts, dict):
                scripts = {}
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
                _MAKE_TEST_TARGET.match(line)
                for line in makefile.read_text(encoding="utf-8").splitlines()
                # A comment (optionally indented) is never a target, so skip it
                # before matching rather than relying on the anchor alone.
                if not line.lstrip().startswith("#")
            ):
                return "make test"
        except OSError:
            pass

    return None
