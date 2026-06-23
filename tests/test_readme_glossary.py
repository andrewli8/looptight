"""The README defines its core jargon for newcomers (adoption-review gap)."""

from __future__ import annotations

from pathlib import Path

_README = Path(__file__).resolve().parent.parent / "README.md"
_TERMS = ("verify", "worktree", "headless", "claim", "swarm", "daemon")


def test_readme_has_glossary_defining_core_terms():
    text = _README.read_text(encoding="utf-8")
    assert "## Glossary" in text
    section = text.split("## Glossary", 1)[1].lower()
    for term in _TERMS:
        assert term in section, f"glossary is missing a definition for {term!r}"


def test_readme_links_to_the_glossary():
    # The prose points newcomers at the glossary anchor.
    assert "(#glossary)" in _README.read_text(encoding="utf-8")
