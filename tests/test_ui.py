"""Contracts for the read-only localhost orchestration view."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from types import MethodType

import pytest

from looptight import ui
from looptight.cli import main


def _expected_inline_hash(page: str, tag: str) -> str:
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    start = page.index(open_tag) + len(open_tag)
    end = page.index(close_tag, start)
    digest = hashlib.sha256(page[start:end].encode()).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


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


def test_csp_uses_inline_hashes_not_unsafe_inline(tmp_path):
    csp = ui.CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in csp
    # Hashes are derived from the served page, so they cannot drift out of sync.
    assert f"script-src {_expected_inline_hash(ui.PAGE, 'script')}" in csp
    assert f"style-src {_expected_inline_hash(ui.PAGE, 'style')}" in csp

    ui.write_state(tmp_path, {"schema_version": 1, "manager": {}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/"
    handler.wfile = BytesIO()
    headers: dict[str, str] = {}
    handler.send_response = MethodType(lambda self, status: None, handler)
    handler.send_header = MethodType(lambda self, name, value: headers.update({name: value}), handler)
    handler.end_headers = MethodType(lambda self: None, handler)

    handler.do_GET()

    assert headers["Content-Security-Policy"] == csp


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


def test_page_serves_status_tally_strip_under_csp(tmp_path):
    page = ui.PAGE
    # The summary strip is part of the served markup and render() fills it from
    # per-status counts derived from state.tasks and state.workers.
    assert 'id="tally"' in page
    assert "function tally()" in page
    assert "render(){tally();" in page
    assert "[...(state.tasks||[]),...(state.workers||[])]" in page

    ui.write_state(tmp_path, {"schema_version": 1, "manager": {}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/"
    handler.wfile = BytesIO()
    headers: dict[str, str] = {}
    response: dict[str, int] = {}
    handler.send_response = MethodType(lambda self, status: response.update(status=status), handler)
    handler.send_header = MethodType(lambda self, name, value: headers.update({name: value}), handler)
    handler.end_headers = MethodType(lambda self: None, handler)

    handler.do_GET()

    assert response["status"] == 200
    assert b'id="tally"' in handler.wfile.getvalue()
    assert headers["Content-Security-Policy"] == ui.CONTENT_SECURITY_POLICY


def test_page_serves_idle_empty_state_guidance(tmp_path):
    page = ui.PAGE
    # An idle, empty dashboard explains its own next step instead of bare "no" lanes.
    assert "looptight swarm --headless" in page
    assert "function guide(" in page
    # Guidance only replaces the lanes when the manager is idle and nothing is queued.
    assert "const idle=(manager.status||'').toLowerCase()==='idle'" in page
    assert "guide('tasks'" in page

    ui.write_state(tmp_path, {"schema_version": 1, "manager": {"status": "idle"}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/"
    handler.wfile = BytesIO()
    headers: dict[str, str] = {}
    handler.send_response = MethodType(lambda self, status: None, handler)
    handler.send_header = MethodType(lambda self, name, value: headers.update({name: value}), handler)
    handler.end_headers = MethodType(lambda self: None, handler)

    handler.do_GET()

    assert b"looptight swarm --headless" in handler.wfile.getvalue()
    assert headers["Content-Security-Policy"] == ui.CONTENT_SECURITY_POLICY


def test_page_keeps_inspector_live_across_polls():
    page = ui.PAGE
    # node() registers each rendered record by id so render() can re-resolve the
    # selection from the latest state instead of leaving the inspector stale.
    assert "records[id]=record;" in page
    assert "render(){tally();records={};" in page
    # After rebuilding the graph, render() refreshes the selected node's detail
    # from the freshly rendered records while preserving the selection.
    assert "if(selected){const fresh=records[selected.id];if(fresh)select(fresh)}" in page


def test_legacy_state_without_timestamp_remains_readable(tmp_path):
    state = {"schema_version": 1, "manager": {"status": "idle"}, "tasks": [], "workers": []}
    path = ui._state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    assert ui.read_state(tmp_path) == state


def test_read_state_returns_empty_on_non_utf8_file(tmp_path):
    # A corrupt (non-UTF-8) state file must degrade to empty_state(), never crash
    # the read-only ui/statusline/status views with a UnicodeDecodeError.
    path = ui._state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe not utf-8")

    assert ui.read_state(tmp_path) == ui.empty_state()


def test_write_state_cleans_up_tmp_when_replace_fails(tmp_path, monkeypatch):
    # If the atomic rename fails after the temp file is written, no stale .tmp
    # may be left beside the state path; the error propagates.
    tmp = ui._state_path(tmp_path).with_suffix(".tmp")

    def boom(src, dst):
        raise OSError("cross-device rename")

    monkeypatch.setattr("looptight.fsutil.os.replace", boom)
    with pytest.raises(OSError):
        ui.write_state(tmp_path, {"schema_version": 1})
    assert not tmp.exists()


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


def test_render_state_panel_summarizes_workers():
    from looptight.ui import render_state_panel

    state = {
        "schema_version": 1,
        "manager": {"status": "running"},
        "tasks": [
            {"id": "t1", "goal": "Fix the timeout path", "source": "todo", "status": "running"},
            {"id": "t2", "goal": "Cover the retry case", "source": "lint", "status": "merged"},
        ],
        "workers": [
            {"number": 1, "task_id": "t1", "status": "running", "error": None},
            {"number": 2, "task_id": "t2", "status": "merged", "error": None},
        ],
        "updated_at": "2026-06-23T00:00:00Z",
    }
    panel = render_state_panel(state)
    assert "running 1" in panel and "merged 1" in panel  # status tally
    assert "#1" in panel and "#2" in panel  # per-worker lines
    assert "Fix the timeout path" in panel  # task goal joined by task_id


def test_render_state_panel_empty_without_workers():
    from looptight.ui import render_state_panel

    assert render_state_panel({"manager": {"status": "idle"}, "workers": []}) == ""


def test_statusline_summarizes_workers_or_idle():
    from looptight.ui import statusline

    assert statusline({"workers": []}) == "looptight: idle"
    line = statusline({"workers": [
        {"number": 1, "status": "running"},
        {"number": 2, "status": "merged"},
        {"number": 3, "status": "running"},
    ]})
    assert line.startswith("looptight:")
    assert "2 running" in line and "1 merged" in line


def test_ui_handler_404_for_unknown_path(tmp_path):
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/unknown/path"
    errors: list[int] = []
    handler.send_error = MethodType(lambda self, code: errors.append(code), handler)
    handler.send_response = MethodType(lambda self, code: (_ for _ in ()).throw(AssertionError("send_response must not be called on 404")), handler)

    handler.do_GET()

    assert errors == [404]
