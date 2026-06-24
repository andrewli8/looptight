"""Doc-accuracy checks: documented surfaces match the CLI."""

from __future__ import annotations

from pathlib import Path

_DAEMON_DOC = Path(__file__).resolve().parent.parent / "docs" / "daemon.md"


def test_daemon_doc_documents_on_fault_hook():
    text = _DAEMON_DOC.read_text(encoding="utf-8")
    assert "--on-fault" in text
    for field in ("cycle", "reason", "backoff_s", "last_error"):
        assert field in text, f"daemon.md does not name the {field!r} payload field"


_README = Path(__file__).resolve().parent.parent / "README.md"


def test_readme_documents_polyglot_discovery():
    text = _README.read_text(encoding="utf-8")
    assert "__tests__" in text, "README does not mention colocated JS/TS test discovery"
    assert "it.skip" in text, "README does not mention JS/TS skip discovery"


def test_readme_documents_the_goal_command():
    text = _README.read_text(encoding="utf-8")
    assert "looptight goal" in text, "README does not document the goal command"
    for flag in ("--done", "--continuous", "--max-iterations"):
        assert flag in text, f"README does not document goal's {flag}"
    assert "/loop until: looptight goal check" in text, "README lacks the continuous recipe"


_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_SRC = Path(__file__).resolve().parent.parent / "src"


def test_readme_dependency_claim_matches_zero_runtime_deps():
    # The package ships with no third-party runtime dependency (pyproject declares an
    # empty `dependencies`, and the stdlib Console replaced rich). The README must not
    # claim a `rich` (or any) runtime dependency, or it contradicts the core principle.
    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    assert "dependencies = []" in pyproject, "pyproject no longer declares zero runtime deps"

    src_imports_rich = any(
        ("import rich" in path.read_text(encoding="utf-8"))
        or ("from rich" in path.read_text(encoding="utf-8"))
        for path in _SRC.rglob("*.py")
    )
    assert not src_imports_rich, "src/ imports rich; the README claim would be accurate again"

    readme = _README.read_text(encoding="utf-8")
    assert "beyond `rich`" not in readme, "README still claims a stale `rich` runtime dependency"
    assert "no third-party runtime" in readme, "README should state there are no runtime deps"
