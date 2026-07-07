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
# A Make `check` rule (GNU/autotools convention for running tests, and a common
# "run all checks" target), matched the same way and used as a fallback after `test`.
_MAKE_CHECK_TARGET = re.compile(r"check\s*:(?!:?=)")


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
    ("deno.json", "deno test"),
    ("deno.jsonc", "deno test"),
    ("mix.exs", "mix test"),        # Elixir: mix is the single test runner
    ("Package.swift", "swift test"),  # SwiftPM
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
            test_script = scripts.get("test")
            # `npm init` writes a placeholder (`echo "Error: no test specified" &&
            # exit 1`) that always fails. Claiming `npm test` for it would stall the
            # loop on a verify that can never pass, so treat it as no test at all.
            if isinstance(test_script, str) and "no test specified" not in test_script.lower():
                return "npm test"
        except (ValueError, OSError):
            pass

    # uv-managed projects have uv.lock alongside pyproject.toml. In a fresh
    # uv-only environment pytest is not on PATH, so the correct command is
    # `uv run pytest -q`, not the bare `pytest -q` that _VERIFY_RULES would return.
    if (base / "pyproject.toml").is_file() and (base / "uv.lock").is_file():
        return "uv run pytest -q"
    if (base / "pyproject.toml").is_file() and (base / "poetry.lock").is_file():
        return "poetry run pytest -q"

    for marker, command in _VERIFY_RULES:
        if (base / marker).is_file():
            return command

    # JVM build tools standardly ship a committed wrapper (gradlew/mvnw) that is
    # version-pinned and needs no global install — the CI-standard way to run them —
    # so prefer it when present, else the bare tool on PATH (like the npm branch, we
    # avoid claiming a command that probably will not run).
    if (base / "build.gradle").is_file() or (base / "build.gradle.kts").is_file():
        return "./gradlew test" if (base / "gradlew").is_file() else "gradle test"
    if (base / "pom.xml").is_file():
        return "./mvnw test" if (base / "mvnw").is_file() else "mvn test"

    # .NET project/solution files are arbitrarily named, so match by extension. Any
    # of them maps to the unambiguous `dotnet test`.
    if any(any(base.glob(f"*{ext}")) for ext in (".sln", ".csproj", ".fsproj", ".vbproj")):
        return "dotnet test"

    makefile = base / "Makefile"
    if makefile.is_file():
        runner = _recipe_runner(makefile, "make")
        if runner:
            return runner

    # `just` is a Makefile alternative whose recipes use the same `name:` syntax.
    for just_name in ("justfile", "Justfile", ".justfile"):
        just = base / just_name
        if just.is_file():
            runner = _recipe_runner(just, "just")
            if runner:
                return runner
            break

    # Last resort: a plain Python project may ship pytest tests without any config file
    # (no pyproject/setup.cfg/pytest.ini/tox.ini). Detect pytest from the test files
    # themselves — in the root or a conventional tests/ dir — so `init` reports a real
    # detection instead of falling back to the bare default with "no test command detected".
    for directory in (base, base / "tests", base / "test"):
        if not directory.is_dir():
            continue
        if (
            (directory / "conftest.py").is_file()
            or any(directory.glob("test_*.py"))
            or any(directory.glob("*_test.py"))
        ):
            return "pytest -q"

    return None


def _recipe_runner(path: Path, tool: str) -> str | None:
    """``<tool> test`` or ``<tool> check`` if ``path`` (a Makefile/justfile) defines a
    `test:`/`check:` recipe (`test` preferred), else None. An unreadable file yields
    None, matching the other detection branches."""
    try:
        # A comment (optionally indented) is never a target/recipe, so skip it before
        # matching rather than relying on the anchor alone.
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        ]
    except (OSError, ValueError):
        # ValueError covers a non-UTF-8 file's UnicodeDecodeError, matching the
        # package.json branch above: an unreadable file falls through.
        return None
    if any(_MAKE_TEST_TARGET.match(line) for line in lines):
        return f"{tool} test"
    if any(_MAKE_CHECK_TARGET.match(line) for line in lines):
        return f"{tool} check"
    return None
