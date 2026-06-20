"""Contracts for the read-only localhost orchestration view."""

from __future__ import annotations

import json
from io import BytesIO
from types import MethodType

import pytest

from looptight import ui
from looptight.cli import main


def test_server_binds_loopback_and_serves_versioned_state(tmp_path, monkeypatch):
    state = {
        "schema_version": 1,
        "manager": {"status": "running"},
        "tasks": [{"id": "task-a", "goal": "Build the graph", "status": "running"}],
        "workers": [{"number": 1, "task_id": "task-a", "status": "ready", "error": None}],
    }
    monkeypatch.setattr("looptight.ui._utc_timestamp", lambda: "2026-06-20T12:00:00Z")
    ui.write_state(tmp_path, state)
    handler_type = ui._handler(tmp_path)
    handler = object.__new__(handler_type)
    handler.path = "/api/state"
    handler.wfile = BytesIO()
    response = {"headers": {}}
    handler.send_response = MethodType(lambda self, status: response.update(status=status), handler)
    handler.send_header = MethodType(
        lambda self, name, value: response["headers"].update({name: value}), handler
    )
    handler.end_headers = MethodType(lambda self: None, handler)

    handler.do_GET()

    assert response["status"] == 200
    assert response["headers"]["Cache-Control"] == "no-store"
    assert response["headers"]["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response["headers"]["Content-Security-Policy"]
    assert json.loads(handler.wfile.getvalue()) == {
        **state,
        "updated_at": "2026-06-20T12:00:00Z",
    }

    constructed = {}

    class FakeServer:
        def __init__(self, address, handler):
            constructed.update(address=address, handler=handler)

    original = ui.ThreadingHTTPServer
    ui.ThreadingHTTPServer = FakeServer
    try:
        assert isinstance(ui.create_server(tmp_path, port=9123), FakeServer)
    finally:
        ui.ThreadingHTTPServer = original
    assert constructed["address"] == ("127.0.0.1", 9123)


def test_page_is_dependency_free_accessible_polling_node_graph(tmp_path):
    page = ui.PAGE
    assert "https://" not in page
    assert 'aria-label="Swarm orchestration graph"' in page
    assert "<svg" in page
    assert "/api/state" in page
    assert "setInterval" in page
    assert "manager" in page and "tasks" in page and "workers" in page


def test_page_supports_read_only_keyboard_selection_and_status_filters():
    page = ui.PAGE
    assert 'aria-label="Filter nodes by status"' in page
    assert 'role="status" aria-live="polite"' in page
    assert "e.key==='Enter'||e.key===' '" in page
    assert "setAttribute('aria-pressed'" in page
    assert "filter(t=>visible(t.status))" in page
    assert "filter(w=>visible(w.status))" in page
    assert "state=await r.json();render()" in page
    assert "addEventListener('resize',render)" in page


def test_page_reports_event_age_without_health_inference():
    page = ui.PAGE
    assert 'id="age">UNKNOWN' in page
    assert "function eventAge(timestamp,now=Date.now())" in page
    assert "eventAge(state.updated_at)" in page
    assert "stale" not in page.lower()


def test_legacy_state_without_timestamp_remains_readable(tmp_path):
    state = {"schema_version": 1, "manager": {"status": "idle"}, "tasks": [], "workers": []}
    path = ui._state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    assert ui.read_state(tmp_path) == state


def test_ui_command_passes_port_to_server(tmp_path, monkeypatch):
    called = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "looptight.cli.serve_ui",
        lambda root, port: called.update(root=root, port=port),
    )

    assert main(["ui", "--port", "9123"]) == 0
    assert called == {"root": tmp_path, "port": 9123}


def test_ui_command_rejects_out_of_range_port():
    with pytest.raises(SystemExit) as exc:
        main(["ui", "--port", "65536"])
    assert exc.value.code == 2
