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


def test_host_is_loopback_accepts_loopback_and_rejects_remote():
    assert ui._host_is_loopback("127.0.0.1:8765")
    assert ui._host_is_loopback("localhost")
    assert ui._host_is_loopback("[::1]:8765")
    assert ui._host_is_loopback(None)  # HTTP/1.0 / direct tool: no rebinding vector
    assert ui._host_is_loopback("")
    assert not ui._host_is_loopback("evil.example.com")
    assert not ui._host_is_loopback("attacker.test:8765")


def test_host_is_loopback_accepts_bracketed_ipv6_without_port():
    # ui.py:397-398 — raw[1:].split("]", 1)[0] extracts "::1" from "[::1]" even
    # when there is no trailing ":port"; the portless case was previously untested.
    assert ui._host_is_loopback("[::1]")


def test_do_get_rejects_a_non_loopback_host(tmp_path):
    # DNS-rebinding hardening: a request whose Host is a remote domain (rebound to 127.0.0.1)
    # must be refused, even though it reached the loopback socket.
    ui.write_state(tmp_path, {"schema_version": 1, "manager": {}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/api/state"
    handler.headers = {"Host": "evil.example.com"}
    errors: dict = {}
    handler.send_error = MethodType(lambda self, code, *a: errors.update(code=code), handler)

    handler.do_GET()

    assert errors["code"] == 403


def test_session_view_is_two_lane_not_three():
    # In session mode the swarm workers lane is dropped so the view is structurally a session
    # (manager → task), not a 3-lane swarm.
    assert "classList.toggle('session',soloMode)" in ui.PAGE  # 2-lane for session and goal modes
    assert ".graph.session #workers{display:none}" in ui.PAGE


def test_manager_node_is_mode_aware():
    # The manager node must not claim to be a swarm orchestrator in session/goal mode; render()
    # picks the label/detail by mode.
    assert "mode==='session'" in ui.PAGE or "mgrTitle" in ui.PAGE
    assert "your next / verify loop" in ui.PAGE  # session-mode detail
    assert "deterministic integration gate" in ui.PAGE  # swarm-mode detail still present


def test_worker_node_shows_the_task_goal_not_just_the_id():
    # A worker with no error should read as "what it's building", not an opaque task id; render()
    # looks the goal up from state.tasks by task_id.
    assert "taskGoals" in ui.PAGE
    assert "taskGoals[w.task_id]" in ui.PAGE


def test_task_node_surfaces_source_provenance():
    # The swarm writes a `source` per task (todo/lint/status-next/...); the graph should show
    # that provenance as the task node's detail, not the opaque internal id.
    assert "t.source?`source" in ui.PAGE


def test_statusline_appends_the_verify_verdict_when_present():
    # The always-visible status bar should show whether the last gate passed.
    state = {
        "manager": {"status": "session", "verify": "pass"},
        "tasks": [{"id": "t1", "goal": "fix the parser", "status": "claimed"}],
        "workers": [],
    }
    assert ui.statusline(state) == "looptight: fix the parser · pass"
    # No verdict -> unchanged.
    no_verify = {"manager": {"status": "session"}, "tasks": [{"id": "t1", "goal": "fix the parser"}], "workers": []}
    assert ui.statusline(no_verify) == "looptight: fix the parser"


def test_statusline_shows_the_current_task_when_no_workers():
    # On the default loop there are no swarm workers; the bar should show what's being worked,
    # not "idle".
    state = {"workers": [], "tasks": [{"id": "t1", "goal": "fix the parser", "status": "claimed"}]}
    assert ui.statusline(state) == "looptight: fix the parser"


def test_statusline_truncates_a_long_task_goal():
    state = {"workers": [], "tasks": [{"id": "t1", "goal": "x" * 60, "status": "claimed"}]}
    line = ui.statusline(state)
    assert line.startswith("looptight: ") and line.endswith("…") and len(line) < 70


def test_statusline_workers_win_over_a_task():
    state = {
        "workers": [{"number": 1, "status": "running"}],
        "tasks": [{"id": "t1", "goal": "g", "status": "running"}],
    }
    assert ui.statusline(state) == "looptight: 1 running"  # swarm mode unchanged


def test_statusline_falls_through_to_task_when_workers_is_not_a_list():
    # ui.py:171 — isinstance guard rejects non-list workers value; task mode activates
    state = {"workers": "not-a-list", "tasks": [{"goal": "do X"}]}
    result = ui.statusline(state)
    assert "do X" in result
    assert "workers" not in result


def test_statusline_idle_when_truly_empty():
    assert ui.statusline({"workers": [], "tasks": []}) == "looptight: idle"


def test_statusline_idle_when_task_has_empty_goal_and_id():
    # ui.py:181 — when tasks[0] is present but both "goal" and "id" are empty
    # strings, the `if goal:` branch is skipped and the function returns
    # "looptight: idle". Pinned here so a regression changing the fallback is caught.
    assert ui.statusline({"tasks": [{"goal": "", "id": ""}], "workers": []}) == "looptight: idle"


def test_verdict_round_trips_and_degrades(tmp_path):
    assert ui.read_verdict(tmp_path) is None  # absent
    ui.write_verdict(tmp_path, "pass")
    assert ui.read_verdict(tmp_path) == "pass"
    ui.write_verdict(tmp_path, "fail")  # latest wins
    assert ui.read_verdict(tmp_path) == "fail"
    ui._verdict_path(tmp_path).write_text("not json", encoding="utf-8")
    assert ui.read_verdict(tmp_path) is None  # corrupt → None, never raises


def test_verdict_record_returns_none_for_non_dict_json(tmp_path):
    path = ui._verdict_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    assert ui._verdict_record(tmp_path) is None


def test_read_verdict_returns_none_for_non_string_status(tmp_path):
    path = ui._verdict_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": 42}) + "\n", encoding="utf-8")
    assert ui.read_verdict(tmp_path) is None


def test_with_session_task_includes_the_verify_verdict_and_freshness(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ui, "_active_session_task", lambda root: {"id": "a", "goal": "g", "source": "", "status": "claimed"}
    )
    monkeypatch.setattr(
        ui, "_verdict_record", lambda root: {"status": "pass", "at": "2026-06-20T12:00:00Z"}
    )
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["verify"] == "pass"
    assert state["updated_at"] == "2026-06-20T12:00:00Z"  # footer freshness, not UNKNOWN


def test_with_session_task_no_verdict_leaves_no_badge_or_timestamp(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ui, "_active_session_task", lambda root: {"id": "a", "goal": "g", "source": "", "status": "claimed"}
    )
    monkeypatch.setattr(ui, "_verdict_record", lambda root: None)
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert "verify" not in state["manager"]
    assert state["updated_at"] is None  # degrades to UNKNOWN, never raises


def test_with_session_task_verdict_with_status_but_no_at_sets_badge_not_timestamp(monkeypatch, tmp_path):
    # ui.py:267,270 — the two `record`-guarded branches are independent: a record
    # with a valid string status but no "at" key must set the verify badge without
    # touching updated_at. A mutation removing the isinstance(..., str) guard on
    # line 270 would set updated_at to the record dict rather than leaving it None.
    monkeypatch.setattr(
        ui, "_active_session_task", lambda root: {"id": "a", "goal": "g", "source": "", "status": "claimed"}
    )
    monkeypatch.setattr(ui, "_verdict_record", lambda root: {"status": "pass"})  # no "at" key
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["verify"] == "pass"  # badge is set from the status
    assert state["updated_at"] is None  # no "at" → footer stays UNKNOWN


def test_page_renders_the_session_verify_verdict():
    assert "manager.verify" in ui.PAGE  # the session manager detail shows the last verdict


def test_active_goal_view_renders_the_vision_and_iteration(monkeypatch, tmp_path):
    from looptight.goal import Goal

    monkeypatch.setattr("looptight.goal.read_goal", lambda root: Goal(vision="ship the landing page", iteration=3))
    view = ui._active_goal_view(tmp_path)
    assert view["goal"] == "ship the landing page"
    assert "iteration 3" in view["source"]
    monkeypatch.setattr("looptight.goal.read_goal", lambda root: None)
    assert ui._active_goal_view(tmp_path) is None


def test_with_session_task_overlays_an_active_goal(monkeypatch, tmp_path):
    # No swarm, no session claim, but a build goal is active → represent it (manager "goal").
    monkeypatch.setattr(ui, "_active_session_task", lambda root: None)
    monkeypatch.setattr(
        ui,
        "_active_goal_view",
        lambda root: {"id": "goal", "goal": "ship the landing page", "source": "goal · iteration 3", "status": "running"},
    )
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["status"] == "goal"
    assert state["tasks"][0]["goal"] == "ship the landing page"


def test_with_session_task_goal_includes_the_verify_verdict_and_freshness(monkeypatch, tmp_path):
    # Goal-mode increments are verify-gated too, so the goal overlay carries the verdict like
    # the session overlay does — pass/fail is the goal's build-health signal.
    monkeypatch.setattr(ui, "_active_session_task", lambda root: None)
    monkeypatch.setattr(
        ui,
        "_active_goal_view",
        lambda root: {"id": "goal", "goal": "ship the landing page", "source": "goal · iteration 3", "status": "running"},
    )
    monkeypatch.setattr(ui, "_verdict_record", lambda root: {"status": "pass", "at": "2026-06-20T12:00:00Z"})
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["status"] == "goal"
    assert state["manager"]["verify"] == "pass"
    assert state["updated_at"] == "2026-06-20T12:00:00Z"  # footer freshness, not UNKNOWN


def test_with_session_task_goal_no_verdict_leaves_no_badge(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "_active_session_task", lambda root: None)
    monkeypatch.setattr(
        ui,
        "_active_goal_view",
        lambda root: {"id": "goal", "goal": "v", "source": "", "status": "running"},
    )
    monkeypatch.setattr(ui, "_verdict_record", lambda root: None)
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert "verify" not in state["manager"]
    assert state["updated_at"] is None  # degrades to UNKNOWN, never raises


def test_session_claim_takes_precedence_over_a_goal(monkeypatch, tmp_path):
    monkeypatch.setattr(
        ui, "_active_session_task", lambda root: {"id": "t", "goal": "a claimed task", "source": "", "status": "claimed"}
    )
    monkeypatch.setattr(ui, "_active_goal_view", lambda root: {"id": "goal", "goal": "v", "source": "", "status": "running"})
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["status"] == "session"
    assert state["tasks"][0]["goal"] == "a claimed task"


def test_page_marks_a_failing_verdict_for_legibility():
    # A failing gate is the most important negative signal; it must not read like a passing one.
    # The page adds a verify-fail class only when manager.verify is present and not "pass", and a
    # CSS rule colors that manager detail red (the established attention color).
    page = ui.PAGE
    assert "manager.verify&&manager.verify!=='pass'" in page  # guarded: present and not pass
    assert "verify-fail" in page
    assert ".manager.verify-fail .detail{color:var(--red)}" in page


def test_page_colors_complete_status_badges_to_match_the_node_border():
    # The page has one color language: acid=active, red=attention, cyan=complete. The node
    # left-border and the tally cards both honor it. The status badge must too: a merged/complete
    # node carries a cyan left-border, so a green (acid) badge on the same card contradicts it and
    # reads as "still active". Attention statuses already get a red badge; complete needs cyan.
    page = ui.PAGE
    assert (
        ".merged .status,.complete .status,.completed .status,.passed .status"
        "{background:var(--cyan)}" in page
    )
    # The complete-badge rule must use the same accent the node border and tally already use,
    # so the three surfaces never disagree about what "complete" looks like.
    assert ".task.merged,.task.complete,.task.completed,.task.passed{border-left-color:var(--cyan)}" in page
    assert ".stat.complete{border-top-color:var(--cyan)}" in page


def test_page_renders_goal_mode():
    assert "mode==='goal'" in ui.PAGE
    assert "your goal build loop" in ui.PAGE


def test_page_goal_detail_shows_the_verify_verdict():
    # The goal-mode manager detail appends the last verdict when present, like session mode.
    page = ui.PAGE
    detail = page[page.index("mgrDetail="):]
    goal_branch = detail[: detail.index(":mode==='session'")]  # the goal-mode arm of mgrDetail
    assert "manager.verify" in goal_branch and "verify:" in goal_branch


def test_with_session_task_overlays_the_claim_when_no_swarm(monkeypatch, tmp_path):
    # On the default loop the state file is empty; the view should surface the session's claimed
    # task (manager "session", one task) instead of a bare idle screen.
    monkeypatch.setattr(
        ui,
        "_active_session_task",
        lambda root: {"id": "abc", "goal": "fix the parser", "source": "todo", "status": "claimed"},
    )
    state = ui._with_session_task(ui.empty_state(), tmp_path)
    assert state["manager"]["status"] == "session"
    assert state["tasks"][0]["goal"] == "fix the parser"
    assert ui.summarize(state) == {"total": 1, "active": 1, "attention": 0, "complete": 0}


def test_with_session_task_leaves_live_swarm_state_unchanged(monkeypatch, tmp_path):
    # A running swarm publishes real state; the session overlay must not clobber it.
    monkeypatch.setattr(
        ui, "_active_session_task", lambda root: {"id": "x", "goal": "y", "source": "", "status": "claimed"}
    )
    swarm = {**ui.empty_state(), "tasks": [{"id": "w1", "goal": "swarm task", "status": "running"}]}
    state = ui._with_session_task(swarm, tmp_path)
    assert state["tasks"][0]["goal"] == "swarm task"  # unchanged; no overlay


def test_with_session_task_idle_when_no_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "_active_session_task", lambda root: None)
    assert ui._with_session_task(ui.empty_state(), tmp_path) == ui.empty_state()


def test_summarize_is_a_coherent_task_centric_partition():
    # The tally's four cells must describe ONE population: total = tasks, with
    # active/attention/complete as subsets of those tasks. A worker's status must not
    # inflate the task counts (the old client tally mixed tasks+workers into the breakdown).
    state = {
        "tasks": [
            {"id": "a", "status": "running"},  # active
            {"id": "b", "status": "merged"},  # complete
            {"id": "c", "status": "failed"},  # attention
            {"id": "d", "status": "queued"},  # pending (no group)
        ],
        "workers": [
            {"number": 1, "status": "conflict"},  # attention status, but a worker
            {"number": 2, "status": "running"},  # active status, but a worker
        ],
    }
    s = ui.summarize(state)
    assert s["total"] == 4  # tasks only, not tasks+workers
    assert s["active"] == 1 and s["attention"] == 1 and s["complete"] == 1
    assert s["active"] + s["attention"] + s["complete"] <= s["total"]  # a coherent subset


def test_summarize_buckets_every_real_swarm_status():
    # Every status the swarm actually publishes must land in a tally bucket, so the four cells
    # stay coherent: active + attention + complete == total. verified (awaiting merge), limited
    # (hit a usage cap), and interrupted were previously unbucketed and silently undercounted.
    real = [
        "ready", "running", "claimed", "integrating", "verified",  # in flight
        "merged",  # complete
        "failed", "error", "conflict", "timeout", "limited", "interrupted",  # attention
    ]
    state = {"tasks": [{"id": str(i), "status": s} for i, s in enumerate(real)]}
    s = ui.summarize(state)
    assert s["total"] == len(real)
    assert s["active"] + s["attention"] + s["complete"] == s["total"]  # no status falls through
    assert "verified" in ui._STATUS_GROUPS["active"]  # passed verify, still integrating
    assert {"limited", "interrupted"} <= ui._STATUS_GROUPS["attention"]  # could not finish


def test_page_filter_groups_match_the_python_status_groups():
    # The JS `groups` set drives the filter buttons; it must mirror _STATUS_GROUPS so the filters
    # and the tally agree on which statuses are active/attention/complete.
    import re

    block = ui.PAGE[ui.PAGE.index("const groups={"):]
    block = block[: block.index("};") + 1]
    parsed = {
        m.group(1): set(re.findall(r"'([^']*)'", m.group(2)))
        for m in re.finditer(r"(\w+):new Set\(\[([^\]]*)\]\)", block)
    }
    assert parsed == {k: set(v) for k, v in ui._STATUS_GROUPS.items()}


def test_small_text_is_at_least_11px():
    # The smallest UI text was 10px (below a comfortable readability floor); fonts are now >= 11px.
    page = ui.PAGE
    assert "font-size:10px" not in page
    assert "font:700 10px" not in page
    assert "font-size:11px" in page  # the bumped small text
    # 10px spacing values (gap/padding/margin) are unaffected
    assert "padding:10px 13px" in page


def test_card_border_meets_non_text_contrast():
    # The --line border is the sole boundary cue for cards/stats/filters/nodes (the panel fill and
    # shadow are imperceptible), so it must meet WCAG 1.4.11 (3:1) against --panel. Compute it.
    import re

    page = ui.PAGE

    def rgb(name):
        h = re.search(rf"--{name}:(#[0-9a-fA-F]{{6}})", page).group(1)[1:]
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

    def lum(c):
        chan = [(x / 255) for x in c]
        chan = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in chan]
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

    line_l, panel_l = lum(rgb("line")), lum(rgb("panel"))
    hi, lo = max(line_l, panel_l), min(line_l, panel_l)
    ratio = (hi + 0.05) / (lo + 0.05)
    assert ratio >= 3.0, f"--line on --panel is {ratio:.2f}:1, below WCAG 1.4.11 3:1"
    # the hardcoded wire-arrow fill must track --line so the arrowhead stays consistent
    line_hex = re.search(r"--line:(#[0-9a-fA-F]{6})", page).group(1)
    assert f'fill="{line_hex}"' in page


def test_tally_total_cell_is_neutral_not_the_active_color():
    # The four tally cells are a legend: total=neutral, active=acid, attention=red, complete=cyan.
    # total (no class) must NOT default to the acid border that marks active, or it reads as one.
    css = ui.PAGE
    import re

    stat_default = re.search(r"\.stat\{[^}]*\}", css).group(0)
    assert "border-top:3px solid var(--line)" in stat_default  # neutral default for total
    assert "var(--acid)" not in stat_default  # total no longer wears the active color
    assert ".stat.active{border-top-color:var(--acid)}" in css  # active is explicitly acid
    assert ".stat.attention{border-top-color:var(--red)}" in css
    assert ".stat.complete{border-top-color:var(--cyan)}" in css


def test_accessibility_semantics_connection_label_and_focus():
    page = ui.PAGE
    # (a) connection status is a live region, and update() sets it only on change (no poll spam)
    conn = page[page.index('id="connection"'):page.index('id="connection"') + 70]
    assert 'role="status"' in conn and 'aria-live="polite"' in conn
    assert "if(c.textContent!=='live / polling')" in page
    assert "if(c.textContent!=='state unavailable')" in page
    # (b) a missing status does not render the literal "undefined" in the node label
    assert "status ${status||'unknown'}" in page
    # (c) the filter buttons get a visible focus style like the nodes
    assert ".filter:focus-visible{" in page


def test_lanes_are_labeled_groups():
    # Each orchestration lane should announce as a labeled region for screen-reader navigation.
    page = ui.PAGE
    for lane in ("manager", "tasks", "workers"):
        assert f'id="{lane}" role="group" aria-labelledby="{lane}-title"' in page
        assert f'class="lane-title" id="{lane}-title"' in page


def test_live_regions_skip_unchanged_updates():
    # The tally and inspector are aria-live="polite" regions; they must not rebuild the DOM on
    # every 1.5s poll when nothing changed, or a screen reader re-announces them continuously.
    page = ui.PAGE
    tally_fn = page[page.index("function tally("):page.index("function ", page.index("function tally(") + 12)]
    assert "lastTallyKey" in tally_fn and "return" in tally_fn  # early-return on an unchanged key
    # the poll-time inspector re-render is guarded so it only re-selects on a real change
    assert "lastInspectorKey" in page


def test_unknown_status_gets_a_neutral_badge_not_a_green_one():
    # Safe-by-default: a task/worker status outside the known set (corrupt state or a future
    # status not yet added to the groups) must not render the green "healthy" badge. It is tagged
    # via the existing groups (no new status list) and given a muted badge; the manager is exempt.
    page = ui.PAGE
    assert "unknown-status" in page
    assert ".unknown-status .status{background:var(--muted)}" in page  # neutral, not acid
    node_fn = page[page.index("function node(kind"):page.index("function fill(")]
    assert "groups.active.has" in node_fn  # reuses the existing group knowledge
    assert "kind==='manager'" in node_fn  # the manager's mode status is never flagged unknown


def test_node_border_colors_match_the_tally_legend():
    # The graph must use the same color legend as the tally: acid=active, red=attention,
    # cyan=complete. Otherwise an active task (cyan default) looks identical to a complete one
    # and contradicts the acid manager. Extract the status tokens from each border-color rule.
    import re

    css = ui.PAGE

    def statuses_for(color):
        found = set()
        for m in re.finditer(r"([^{}]*)\{border-left-color:var\(--%s\)\}" % color, css):
            found |= set(re.findall(r"\.(?:node|task)\.(\w+)", m.group(1)))
        return found

    assert ui._STATUS_GROUPS["active"] <= statuses_for("acid")  # active tasks read acid, not cyan
    assert ui._STATUS_GROUPS["attention"] <= statuses_for("red")  # incl. limited/interrupted
    assert ui._STATUS_GROUPS["complete"] <= statuses_for("cyan")


def test_attention_badge_covers_limited_and_interrupted():
    # The status badge background goes red for every attention status, including the two that
    # were previously unstyled (limited/interrupted).
    css = ui.PAGE
    badge_rule = css[css.index(".status{"):]
    badge_rule = badge_rule[: badge_rule.index("{background:var(--red)}") + len("{background:var(--red)}")]
    for status in ui._STATUS_GROUPS["attention"]:
        assert f".{status} .status" in badge_rule


def test_summarize_tolerates_empty_and_malformed_state():
    assert ui.summarize({}) == {"total": 0, "active": 0, "attention": 0, "complete": 0}
    assert ui.summarize({"tasks": [None, "x", {"status": "running"}]})["total"] == 1


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
    handler.headers = {}
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
        "summary": ui.summarize({**state, "updated_at": "2026-06-20T12:00:00Z"}),
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
    handler.headers = {}
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
    # The summary strip is part of the served markup and render() fills it from the
    # server-computed, coherent `state.summary` (not a separate, inconsistent client tally).
    assert 'id="tally"' in page
    assert "function tally()" in page
    assert "render(){tally();" in page
    assert "state.summary" in page

    ui.write_state(tmp_path, {"schema_version": 1, "manager": {}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/"
    handler.headers = {}
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
    # An idle, empty dashboard explains its own next step (the primary loop) instead of bare lanes.
    assert "looptight next" in page
    assert "function guide(" in page
    # Guidance only replaces the lanes when the manager is idle and nothing is queued.
    assert "const idle=(manager.status||'').toLowerCase()==='idle'" in page
    assert "guide('tasks'" in page

    ui.write_state(tmp_path, {"schema_version": 1, "manager": {"status": "idle"}, "tasks": [], "workers": []})
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/"
    handler.headers = {}
    handler.wfile = BytesIO()
    headers: dict[str, str] = {}
    handler.send_response = MethodType(lambda self, status: None, handler)
    handler.send_header = MethodType(lambda self, name, value: headers.update({name: value}), handler)
    handler.end_headers = MethodType(lambda self: None, handler)

    handler.do_GET()

    assert b"looptight next" in handler.wfile.getvalue()  # the idle guide leads with the primary loop
    assert headers["Content-Security-Policy"] == ui.CONTENT_SECURITY_POLICY


def test_page_keeps_inspector_live_across_polls():
    page = ui.PAGE
    # node() registers each rendered record by id so render() can re-resolve the
    # selection from the latest state instead of leaving the inspector stale.
    assert "records[id]=record;" in page
    assert "render(){tally();records={};" in page
    # After rebuilding the graph, render() refreshes the selected node's detail from the freshly
    # rendered records while preserving the selection — but only when it actually changed, so the
    # aria-live inspector is not re-announced on every poll.
    assert "if(selected){const fresh=records[selected.id];if(fresh){" in page
    assert "if(ik!==lastInspectorKey)select(fresh)" in page


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


def test_read_state_returns_empty_on_malformed_json(tmp_path):
    # ui.py:62 — json.loads() raises json.JSONDecodeError (a ValueError sub-type) for a
    # file that is valid UTF-8 but contains invalid JSON.  The except (OSError, ValueError)
    # handler is documented (ui.py:63) as covering both JSONDecodeError and UnicodeDecodeError,
    # but only the UnicodeDecodeError sub-path is exercised by the sibling test above
    # (non-UTF-8 bytes).  This is the same gap as goal.py:56 (fixed by
    # test_read_goal_returns_none_on_malformed_json).
    path = ui._state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ broken json", encoding="utf-8")

    assert ui.read_state(tmp_path) == ui.empty_state()


def test_read_state_returns_empty_when_git_not_found(tmp_path, monkeypatch):
    # ui.py:25 — _state_path calls subprocess.run(["git", ...]) without a
    # try/except OSError, so read_state raises FileNotFoundError (OSError subclass)
    # when git is absent from PATH instead of returning empty_state().
    # Sibling of the same guard in coordinator_path (coordinator.py:301) and
    # claim_dir (claims.py:47).
    monkeypatch.setattr(ui.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(OSError("git not found")))
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


def test_ui_command_reports_bind_failure_without_traceback(tmp_path, monkeypatch, capsys):
    # A port already in use must surface as an actionable line, not a raw OSError traceback.
    monkeypatch.chdir(tmp_path)

    def boom(root, port):
        raise OSError(48, "Address already in use")

    monkeypatch.setattr("looptight.cli.serve_ui", boom)
    assert main(["ui", "--port", "8801"]) == 2
    out = capsys.readouterr().out
    assert "8801" in out and "port may be in use" in out


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
    assert "(1 running, 1 merged)" in panel  # tally in count-status order, matching the statusline
    assert "#1" in panel and "#2" in panel  # per-worker lines
    assert "Fix the timeout path" in panel  # task goal joined by task_id


def test_render_state_panel_empty_without_workers():
    from looptight.ui import render_state_panel

    assert render_state_panel({"manager": {"status": "idle"}, "workers": []}) == ""


def test_render_state_panel_shows_the_session_loop(monkeypatch, tmp_path):
    from looptight.ui import render_state_panel

    # The session/goal overlay (no swarm workers) renders a one-line summary, so `status --watch`
    # shows the current loop instead of "no active workers".
    session = {
        "manager": {"status": "session", "verify": "pass"},
        "tasks": [{"id": "t1", "goal": "fix the parser", "status": "claimed"}],
        "workers": [],
    }
    panel = render_state_panel(session)
    assert "session" in panel and "fix the parser" in panel and "verify: pass" in panel

    goal = {"manager": {"status": "goal"}, "tasks": [{"id": "g", "goal": "ship it"}], "workers": []}
    assert render_state_panel(goal) == "goal: ship it"
    # workers present -> the worker panel still wins
    swarm = {"manager": {"status": "running"}, "tasks": [], "workers": [{"number": 1, "status": "running"}]}
    assert render_state_panel(swarm).startswith("swarm:")


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


def test_ui_serves_favicon_instead_of_404(tmp_path):
    # The browser auto-requests /favicon.ico on every load; serving an on-brand SVG (declared
    # in <head>) stops the per-load 404 and gives the tab a mark.
    assert '<link rel="icon" href="/favicon.ico"' in ui.PAGE

    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/favicon.ico"
    handler.headers = {}
    handler.wfile = BytesIO()
    response = {"headers": {}}
    handler.send_response = MethodType(lambda self, code: response.update(status=code), handler)
    handler.send_header = MethodType(
        lambda self, name, value: response["headers"].update({name: value}), handler
    )
    handler.end_headers = MethodType(lambda self: None, handler)
    handler.send_error = MethodType(
        lambda self, code: (_ for _ in ()).throw(AssertionError("favicon must not 404")), handler
    )

    handler.do_GET()

    assert response["status"] == 200
    assert response["headers"]["Content-Type"] == "image/svg+xml"
    assert handler.wfile.getvalue().startswith(b"<svg")


def test_ui_handler_404_for_unknown_path(tmp_path):
    handler = object.__new__(ui._handler(tmp_path))
    handler.path = "/unknown/path"
    handler.headers = {}
    errors: list[int] = []
    handler.send_error = MethodType(lambda self, code: errors.append(code), handler)
    handler.send_response = MethodType(lambda self, code: (_ for _ in ()).throw(AssertionError("send_response must not be called on 404")), handler)

    handler.do_GET()

    assert errors == [404]


def test_render_state_panel_and_page_default_a_missing_worker_number():
    from looptight.ui import PAGE, render_state_panel

    state = {
        "manager": {"status": "running"},
        "tasks": [{"id": "t1", "goal": "fix"}],
        "workers": [{"status": "running", "task_id": "t1"}],  # no "number" key
    }
    panel = render_state_panel(state)
    assert "#?" in panel and "#None" not in panel  # malformed worker reads as unknown
    assert "w.number??'?'" in PAGE or "w.number ?? '?'" in PAGE  # browser title fallback


def test_render_state_panel_signals_a_truncated_worker_error():
    from looptight.ui import render_state_panel

    long_error = "merge conflict in src/looptight/coordinator.py at line 412 cannot auto-resolve"
    state = {
        "manager": {"status": "running"},
        "tasks": [{"id": "t1", "goal": "fix"}],  # short goal → not truncated, so any … is the error
        "workers": [{"number": 1, "status": "failed", "task_id": "t1", "error": long_error}],
    }
    panel = render_state_panel(state)
    assert "...]" in panel  # the bracketed error signals truncation instead of reading complete
    assert long_error not in panel  # the full error is not shown verbatim (it was cut)
    # a short error is shown verbatim with no ellipsis
    short = {**state, "workers": [{"number": 1, "status": "failed", "task_id": "t1", "error": "boom"}]}
    assert "[boom]" in render_state_panel(short)


def test_render_state_panel_truncates_goal_and_shows_error():
    from looptight.ui import render_state_panel

    state = {
        "manager": {"status": "running"},
        "tasks": [{"id": "t1", "goal": "x" * 100}],  # long goal → truncated
        "workers": [
            {"number": 1, "status": "running", "task_id": "t1"},
            {"number": 2, "status": "failed", "task_id": "t2", "error": "boom " * 30},
        ],
    }
    panel = render_state_panel(state)
    assert "..." in panel  # the long goal is truncated
    assert "[boom" in panel  # the worker error is shown in brackets


def test_read_state_returns_empty_on_wrong_schema_version(tmp_path):
    import json

    from looptight.ui import _state_path, empty_state, read_state

    path = _state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 99, "workers": []}), encoding="utf-8")
    assert read_state(tmp_path) == empty_state()


def test_read_state_returns_empty_on_valid_json_non_dict(tmp_path):
    import json

    from looptight.ui import _state_path, empty_state, read_state

    path = _state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([]), encoding="utf-8")
    assert read_state(tmp_path) == empty_state()


def test_state_path_in_git_repo_uses_common_dir(tmp_path):
    import subprocess

    from looptight.ui import STATE_FILE, _state_path

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    path = _state_path(tmp_path)
    assert path.name == STATE_FILE
    assert "looptight" in str(path)
    assert ".git" in str(path)  # under the Git common dir, not the .looptight fallback


def test_state_path_uses_absolute_git_common_dir_directly(tmp_path, monkeypatch):
    # ui.py:35 — when git rev-parse --git-common-dir returns an absolute path (linked worktrees),
    # is_absolute() is True so the `common = (root / common).resolve()` line is skipped and the
    # path is used as-is without joining with root.
    import subprocess

    from looptight.ui import STATE_FILE, _state_path

    abs_common = tmp_path / "main" / ".git"
    abs_common.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=str(abs_common) + "\n", stderr="")

    monkeypatch.setattr(ui.subprocess, "run", fake_run)
    result = _state_path(tmp_path / "worktree")
    assert result == abs_common / "looptight" / STATE_FILE


def test_active_session_task_returns_none_on_exception(tmp_path, monkeypatch):
    import looptight.coordinator as _coord

    def _fail(*a, **kw):
        raise RuntimeError("coordinator exploded")

    monkeypatch.setattr(_coord.Coordinator, "open", staticmethod(_fail))
    result = ui._active_session_task(tmp_path)
    assert result is None


def test_active_goal_view_returns_none_on_exception(tmp_path, monkeypatch):
    import looptight.goal as _goal

    def _fail(*a, **kw):
        raise RuntimeError("goal reader exploded")

    monkeypatch.setattr(_goal, "read_goal", _fail)
    result = ui._active_goal_view(tmp_path)
    assert result is None


def test_session_panel_returns_empty_when_task_has_no_goal_or_id():
    # ui.py:118 — the `if not goal: return ""` guard — is reached when
    # tasks[0] has both "goal" and "id" as empty strings (so the `or` fallback
    # also yields an empty string that strips to ""). A well-formed session state
    # but no actual text to display should produce "" rather than "session: ".
    state = {
        "manager": {"status": "session"},
        "tasks": [{"goal": "", "id": ""}],
        "workers": [],
    }
    assert ui._session_panel(state) == ""


def test_session_panel_returns_empty_for_non_session_or_goal_status():
    # ui.py:114 — the `if status not in ("session", "goal")` guard — is
    # exercised here: a state with a valid task list but status="running"
    # must return "" so the session overlay never fires for worker states.
    state = {
        "manager": {"status": "running"},
        "tasks": [{"goal": "do something", "id": "abc123"}],
        "workers": [],
    }
    assert ui._session_panel(state) == ""


def test_session_panel_returns_empty_when_task_is_not_a_dict():
    # ui.py:114 — the `not isinstance(tasks[0], dict)` guard — a tasks list
    # containing a bare string instead of a dict must return "" rather than
    # raising AttributeError when .get() is called on a non-dict.
    state = {
        "manager": {"status": "session"},
        "tasks": ["not a dict"],
        "workers": [],
    }
    assert ui._session_panel(state) == ""


def test_session_panel_goal_mode_appends_verify_suffix():
    # ui.py:121 — the `if isinstance(verify, str) and verify: line += f" · verify: {verify}"`
    # branch is exercised for status="session" by test_render_state_panel_shows_the_session_loop,
    # but NOT for status="goal". A refactor adding `if status == "session":` before the suffix
    # would silently drop the badge for goal mode without breaking any existing test.
    state = {
        "manager": {"status": "goal", "verify": "pass"},
        "tasks": [{"goal": "ship it"}],
    }
    result = ui._session_panel(state)
    assert result == "goal: ship it · verify: pass"


def test_handler_log_message_is_suppressed(tmp_path, capsys):
    # ui.py:440: log_message overrides BaseHTTPRequestHandler's method with a bare
    # return, silencing HTTP request logs.  The override has no direct test.
    handler = object.__new__(ui._handler(tmp_path))
    handler.log_message("GET %s %s", "/", "200")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_serve_ui_starts_server_and_prints_url(tmp_path, monkeypatch, capsys):
    # ui.py:450-454 — serve_ui's body is never driven directly; CLI tests mock
    # serve_ui at the call site. This test verifies serve_forever is called once
    # and the loopback URL is printed to stdout.
    serve_calls: list = []

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def serve_forever(self):
            serve_calls.append(True)

    monkeypatch.setattr(ui, "create_server", lambda root, port=8765: FakeServer())

    ui.serve_ui(tmp_path, port=8765)

    assert len(serve_calls) == 1, "serve_forever must be called exactly once"
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8765" in out
