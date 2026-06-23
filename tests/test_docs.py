"""Doc-accuracy checks: documented surfaces match the CLI."""

from __future__ import annotations

from pathlib import Path

_DAEMON_DOC = Path(__file__).resolve().parent.parent / "docs" / "daemon.md"


def test_daemon_doc_documents_on_fault_hook():
    text = _DAEMON_DOC.read_text(encoding="utf-8")
    assert "--on-fault" in text
    for field in ("cycle", "reason", "backoff_s", "last_error"):
        assert field in text, f"daemon.md does not name the {field!r} payload field"
