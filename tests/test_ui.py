"""Contracts for the read-only localhost orchestration view."""

from __future__ import annotations

import json
from io import BytesIO
from types import MethodType

import pytest

from looptight import ui
from looptight.cli import main


def test_server_binds_loopback_and_serves_versioned_state(tmp_path):
    state = {
        "schema_version": 1,
        "manager": {"status": "running"},
        "tasks": [{"id": "task-a", "goal": "Build the graph", "status": "running"}],
        "workers": [{"number": 1, "task_id": "task-a", "status": "ready", "error": None}],
    }
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
    assert json.loads(handler.wfile.getvalue()) == state

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
