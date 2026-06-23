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
