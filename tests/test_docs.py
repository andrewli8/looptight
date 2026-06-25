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
_DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_usage_doc_documents_polyglot_discovery():
    text = (_DOCS / "usage.md").read_text(encoding="utf-8")
    assert "__tests__" in text, "usage.md does not mention colocated JS/TS test discovery"
    assert "it.skip" in text, "usage.md does not mention JS/TS skip discovery"


def test_goal_doc_documents_the_goal_command():
    text = (_DOCS / "goal.md").read_text(encoding="utf-8")
    assert "looptight goal" in text, "goal.md does not document the goal command"
    for flag in ("--done", "--continuous", "--max-iterations"):
        assert flag in text, f"goal.md does not document goal's {flag}"
    assert "/loop until: looptight goal check" in text, "goal.md lacks the continuous recipe"


def test_readme_links_to_the_moved_docs():
    text = _README.read_text(encoding="utf-8")
    for link in ("docs/usage.md", "docs/goal.md", "docs/unattended.md", "docs/integrations.md"):
        assert link in text, f"README does not link to {link}"


def test_integrations_doc_documents_ci_and_pre_commit():
    text = (_DOCS / "integrations.md").read_text(encoding="utf-8")
    assert "looptight verify" in text, "integrations.md lacks the verify command"
    assert "GitHub Actions" in text, "integrations.md lacks the GitHub Actions recipe"
    assert "pre-commit" in text, "integrations.md lacks the pre-commit recipe"


_ROOT = Path(__file__).resolve().parent.parent


def test_pre_commit_hook_definition_is_shipped():
    text = (_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "id: looptight-verify" in text, "missing the looptight-verify hook id"
    assert "entry: looptight verify" in text, "hook does not run looptight verify"


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
