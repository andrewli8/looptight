"""Dependency-free, read-only localhost view of the latest swarm state."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .fsutil import atomic_write_text

STATE_SCHEMA_VERSION = 1
STATE_FILE = "swarm-state.json"


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _state_path(root: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        common = Path(result.stdout.strip())
        if not common.is_absolute():
            common = (root / common).resolve()
        return common / "looptight" / STATE_FILE
    return root / ".looptight" / STATE_FILE


def empty_state() -> dict[str, object]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "manager": {"status": "idle"},
        "tasks": [],
        "workers": [],
        "updated_at": None,
    }


def write_state(root: Path, state: dict[str, object]) -> None:
    """Atomically publish state outside the tracked worktree."""
    path = _state_path(root)
    payload = {**state, "updated_at": _utc_timestamp()}
    atomic_write_text(path, json.dumps(payload, sort_keys=True) + "\n")


def read_state(root: Path) -> dict[str, object]:
    path = _state_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers json.JSONDecodeError and a non-UTF-8 file's
        # UnicodeDecodeError, so a corrupt state file degrades to empty_state().
        return empty_state()
    if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA_VERSION:
        return empty_state()
    return payload


# Status order for the terminal panel: in-flight first, then terminal outcomes.
_WORKER_STATUS_ORDER = (
    "running", "ready", "verified", "merged", "failed", "conflict", "timeout", "interrupted"
)


def render_state_panel(state: dict[str, object]) -> str:
    """Render swarm/daemon worker state as a compact terminal panel, or "" when
    there are no workers. Pure: takes a state dict (from :func:`read_state`)."""
    workers = state.get("workers") or []
    if not isinstance(workers, list) or not workers:
        return ""
    goals = {
        t.get("id"): str(t.get("goal", ""))
        for t in (state.get("tasks") or [])
        if isinstance(t, dict)
    }
    counts: dict[str, int] = {}
    for worker in workers:
        counts[str(worker.get("status", "?"))] = counts.get(str(worker.get("status", "?")), 0) + 1
    ordered = [s for s in _WORKER_STATUS_ORDER if s in counts]
    ordered += [s for s in counts if s not in _WORKER_STATUS_ORDER]
    tally = ", ".join(f"{status} {counts[status]}" for status in ordered)
    manager = str((state.get("manager") or {}).get("status", "?"))
    lines = [f"swarm: manager {manager} · workers: {len(workers)} ({tally})"]
    for worker in workers:
        goal = goals.get(worker.get("task_id"), "")
        if len(goal) > 63:
            goal = goal[:60] + "..."
        line = f"  #{worker.get('number')} {str(worker.get('status', '?')):<10} " \
               f"{worker.get('task_id', '')}  {goal}".rstrip()
        error = worker.get("error")
        if error:
            line += f"  [{str(error)[:50]}]"
        lines.append(line)
    return "\n".join(lines)


def statusline(state: dict[str, object]) -> str:
    """One-line swarm summary for a status bar (e.g. Claude Code's statusLine).

    `looptight: 3 running · 1 merged`, or `looptight: idle` with no workers."""
    workers = state.get("workers") or []
    if not isinstance(workers, list) or not workers:
        return "looptight: idle"
    counts: dict[str, int] = {}
    for worker in workers:
        counts[str(worker.get("status", "?"))] = counts.get(str(worker.get("status", "?")), 0) + 1
    ordered = [s for s in _WORKER_STATUS_ORDER if s in counts]
    ordered += [s for s in counts if s not in _WORKER_STATUS_ORDER]
    return "looptight: " + " · ".join(f"{counts[s]} {s}" for s in ordered)


#: The status groups the page filters and tallies by, kept here so the server-computed
#: summary and the client's filter use one definition.
_STATUS_GROUPS = {
    "active": frozenset({"ready", "running", "claimed", "integrating"}),
    "attention": frozenset({"failed", "error", "conflict", "timeout"}),
    "complete": frozenset({"complete", "completed", "passed", "merged"}),
}


def summarize(state: dict[str, object]) -> dict[str, int]:
    """Coherent at-a-glance counts for the tally strip.

    ``total`` is the number of tasks, and ``active``/``attention``/``complete`` are subsets
    of those same tasks (so the four cells are one honest population, not the previous mix of
    tasks for ``total`` and tasks+workers for the breakdown). Workers stay visible in the
    graph rather than being folded into these task counts.
    """
    tasks = [t for t in (state.get("tasks") or []) if isinstance(t, dict)]
    counts = {"total": len(tasks), "active": 0, "attention": 0, "complete": 0}
    for task in tasks:
        status = str(task.get("status", "")).lower()
        for group, members in _STATUS_GROUPS.items():
            if status in members:
                counts[group] += 1
                break
    return counts


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Looptight / Swarm Signal</title>
<style>
:root{--ink:#dce7df;--muted:#829087;--panel:#101713;--line:#405047;--acid:#c6ff3d;--amber:#ffbd59;--red:#ff6b5f;--cyan:#63e6df}
*{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--ink);background:#09100c;font:14px/1.45 "Courier New",monospace;background-image:linear-gradient(#18221c55 1px,transparent 1px),linear-gradient(90deg,#18221c55 1px,transparent 1px);background-size:28px 28px}
header{display:flex;align-items:end;justify-content:space-between;padding:28px 32px 20px;border-bottom:1px solid var(--line);background:#09100ce8}h1{margin:0;font:700 clamp(24px,4vw,46px)/.9 Georgia,serif;letter-spacing:-.04em}h1 span{color:var(--acid);font:12px "Courier New",monospace;letter-spacing:.18em;display:block;margin-bottom:10px}.live{color:var(--muted);text-transform:uppercase;letter-spacing:.12em}.live::before{content:"";display:inline-block;width:8px;height:8px;margin-right:9px;border-radius:50%;background:var(--acid);box-shadow:0 0 16px var(--acid)}
main{padding:28px 32px}.tally{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}.stat{flex:1 1 120px;padding:10px 13px;border:1px solid var(--line);border-top:3px solid var(--acid);background:var(--panel)}.stat strong{display:block;font:700 24px Georgia,serif;color:var(--ink)}.stat span{color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase}.stat.attention{border-top-color:var(--red)}.stat.complete{border-top-color:var(--cyan)}.controls{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.filters{display:flex;flex-wrap:wrap;gap:8px}.filter{border:1px solid var(--line);padding:8px 11px;color:var(--muted);background:var(--panel);font:700 10px "Courier New",monospace;letter-spacing:.1em;text-transform:uppercase;cursor:pointer}.filter[aria-pressed="true"]{border-color:var(--acid);color:#061006;background:var(--acid)}.inspector{min-width:min(100%,320px);padding:12px 14px;border-left:2px solid var(--acid);background:var(--panel)}.inspector strong{display:block;color:var(--ink);font:700 15px Georgia,serif}.inspector span{color:var(--muted);font-size:11px;overflow-wrap:anywhere}.graph{position:relative;display:grid;grid-template-columns:minmax(180px,.7fr) minmax(240px,1fr) minmax(220px,1fr);gap:clamp(24px,5vw,90px);min-height:60vh;align-items:center}.lane{display:grid;gap:18px;position:relative;z-index:2}.lane-title{color:var(--muted);font-size:11px;letter-spacing:.2em;text-transform:uppercase}.node{position:relative;padding:18px;background:linear-gradient(135deg,#162019 0%,var(--panel) 70%);border:1px solid var(--line);border-left:4px solid var(--cyan);box-shadow:7px 7px 0 #050906;cursor:pointer}.node:focus{outline:2px solid var(--acid);outline-offset:4px}.node[aria-pressed="true"]{border-color:var(--acid);box-shadow:7px 7px 0 var(--acid)}.node.manager{border-left-color:var(--acid);transform:skewY(-2deg)}.node.worker{border-left-color:var(--amber)}.node.failed,.node.error,.node.conflict,.node.timeout{border-left-color:var(--red)}.eyebrow{color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase}.node h2{font:700 17px Georgia,serif;margin:5px 0 10px}.status{display:inline-block;color:#061006;background:var(--acid);padding:3px 7px;font-size:10px;font-weight:bold;text-transform:uppercase}.failed .status,.error .status,.conflict .status,.timeout .status{background:var(--red)}.detail{color:var(--muted);font-size:12px;overflow-wrap:anywhere}.wires{position:absolute;inset:0;width:100%;height:100%;z-index:1;overflow:visible;pointer-events:none}.wire{stroke:var(--line);stroke-width:1.5;fill:none;marker-end:url(#arrow)}.empty{color:var(--muted);padding:18px;border:1px dashed var(--line)}.guide{color:var(--acid);border-color:var(--acid)}.guide code{color:var(--ink)}footer{padding:16px 32px;color:var(--muted);border-top:1px solid var(--line);font-size:11px}
@media(max-width:760px){header{align-items:start;gap:20px}main{padding:24px 18px}.controls{align-items:stretch;flex-direction:column}.graph{grid-template-columns:1fr;gap:34px;align-items:start}.wires{display:none}}
@media(prefers-reduced-motion:no-preference){.live::before{animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.35;box-shadow:0 0 3px var(--acid)}}}
</style>
</head>
<body>
<header><h1><span>LOOPTIGHT // LOCAL CONTROL</span>Swarm Signal</h1><div class="live" id="connection">connecting</div></header>
<main><div class="tally" id="tally" role="status" aria-live="polite" aria-label="Swarm status tally"></div><div class="controls"><div class="filters" aria-label="Filter nodes by status"><button class="filter" data-filter="all" aria-pressed="true">all</button><button class="filter" data-filter="active" aria-pressed="false">active</button><button class="filter" data-filter="attention" aria-pressed="false">attention</button><button class="filter" data-filter="complete" aria-pressed="false">complete</button></div><div class="inspector" id="inspector" role="status" aria-live="polite"><strong>No node selected</strong><span>Choose a node for details.</span></div></div><section class="graph" id="graph" aria-label="Swarm orchestration graph"><svg class="wires" aria-hidden="true"><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#405047"/></marker></defs><g id="wires"></g></svg><div class="lane" id="manager"><div class="lane-title">manager</div></div><div class="lane" id="tasks"><div class="lane-title">tasks</div></div><div class="lane" id="workers"><div class="lane-title">workers</div></div></section></main>
<footer>READ ONLY · LOOPBACK INTERFACE · STATE SCHEMA <span id="schema">—</span> · LAST EVENT <span id="age">UNKNOWN</span></footer>
<script>
const $=id=>document.getElementById(id);
let state={schema_version:1,manager:{status:'idle'},tasks:[],workers:[]},filter='all',selected=null,records={};
const groups={active:new Set(['ready','running','claimed','integrating']),attention:new Set(['failed','error','conflict','timeout']),complete:new Set(['complete','completed','passed','merged'])};
function visible(status){return filter==='all'||groups[filter].has((status||'').toLowerCase())}
function eventAge(timestamp,now=Date.now()){const age=now-Date.parse(timestamp);if(!timestamp||!Number.isFinite(age)||age<0)return'UNKNOWN';const seconds=Math.floor(age/1000);if(seconds<60)return`${seconds}S AGO`;const minutes=Math.floor(seconds/60);if(minutes<60)return`${minutes}M AGO`;const hours=Math.floor(minutes/60);if(hours<24)return`${hours}H AGO`;return`${Math.floor(hours/24)}D AGO`}
function select(record){selected=record;document.querySelectorAll('.node').forEach(n=>n.setAttribute('aria-pressed',String(n.dataset.node===record.id)));const panel=$('inspector');panel.replaceChildren();const title=document.createElement('strong'),detail=document.createElement('span');title.textContent=`${record.kind} · ${record.title}`;detail.textContent=`status ${record.status||'unknown'} · ${record.detail||'no additional detail'}`;panel.append(title,detail)}
function node(kind,title,status,detail,id){const el=document.createElement('article');el.className=`node ${kind} ${status||''}`;el.tabIndex=0;el.dataset.node=id;el.setAttribute('role','button');el.setAttribute('aria-pressed',String(selected?.id===id));el.setAttribute('aria-label',`${kind} ${title}, status ${status}`);const record={kind,title,status,detail,id};records[id]=record;el.addEventListener('click',()=>select(record));el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(record)}});for(const [cls,text] of [['eyebrow',kind],['title',title],['status',status],['detail',detail]]){const child=document.createElement(cls==='title'?'h2':'div');child.className=cls;child.textContent=text||'';el.append(child)}return el}
function fill(id,items,make){const lane=$(id);lane.querySelectorAll('.node,.empty').forEach(n=>n.remove());if(!items.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=`no ${id}`;lane.append(empty)}else items.forEach(item=>lane.append(make(item)))}
function guide(id,lead,command){const lane=$(id);lane.querySelectorAll('.node,.empty').forEach(n=>n.remove());const el=document.createElement('div');el.className='empty guide';el.append(document.createTextNode(`${lead} `));const code=document.createElement('code');code.textContent=command;el.append(code);lane.append(el)}
function wire(from,to){const a=document.querySelector(`[data-node="${CSS.escape(from)}"]`),b=document.querySelector(`[data-node="${CSS.escape(to)}"]`);if(!a||!b)return;const g=$('graph').getBoundingClientRect(),x1=a.getBoundingClientRect(),x2=b.getBoundingClientRect(),p=document.createElementNS('http://www.w3.org/2000/svg','path');const ax=x1.right-g.left,ay=x1.top+x1.height/2-g.top,bx=x2.left-g.left,by=x2.top+x2.height/2-g.top,m=(ax+bx)/2;p.setAttribute('d',`M${ax},${ay} C${m},${ay} ${m},${by} ${bx},${by}`);p.setAttribute('class','wire');$('wires').append(p)}
function tally(){const s=state.summary||{total:(state.tasks||[]).length,active:0,attention:0,complete:0};const cells=[['total',s.total,''],['active',s.active,'active'],['attention',s.attention,'attention'],['complete',s.complete,'complete']];const strip=$('tally');strip.replaceChildren();cells.forEach(([label,value,cls])=>{const cell=document.createElement('div');cell.className=`stat ${cls}`;const v=document.createElement('strong'),l=document.createElement('span');v.textContent=value;l.textContent=label;cell.append(v,l);strip.append(cell)})}
function render(){tally();records={};const manager=state.manager||{status:'idle'};$('manager').querySelectorAll('.node').forEach(n=>n.remove());$('manager').append(node('manager','orchestrator',manager.status,'deterministic integration gate','manager'));const tasks=(state.tasks||[]).filter(t=>visible(t.status)),workers=(state.workers||[]).filter(w=>visible(w.status));const idle=(manager.status||'').toLowerCase()==='idle'&&!(state.tasks||[]).length&&!(state.workers||[]).length;if(idle){guide('tasks','Idle — start a swarm with','looptight swarm --headless');$('workers').querySelectorAll('.node,.empty').forEach(n=>n.remove())}else{fill('tasks',tasks,t=>node('task',t.goal||t.id,t.status,t.id,`task-${t.id}`));fill('workers',workers,w=>node('worker',`worker ${w.number}`,w.status,w.error||w.task_id||'',`worker-${w.number}`))}$('schema').textContent=state.schema_version;$('age').textContent=eventAge(state.updated_at);$('wires').replaceChildren();tasks.forEach(t=>wire('manager',`task-${t.id}`));workers.forEach(w=>wire(`task-${w.task_id}`,`worker-${w.number}`));if(selected){const fresh=records[selected.id];if(fresh)select(fresh)}}
async function update(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error(r.status);state=await r.json();render();$('connection').textContent='live / polling'}catch(e){$('connection').textContent='state unavailable'}}
document.querySelectorAll('.filter').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;document.querySelectorAll('.filter').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));render()}));
update();setInterval(update,1500);addEventListener('resize',render);
</script>
</body></html>"""


def _inline_hash(tag: str) -> str:
    """SHA-256 CSP source for PAGE's single inline ``<tag>`` element.

    Deriving the hash from the served page means a nonce-free, ``unsafe-inline``
    free policy that can never drift out of sync when the page is edited.
    """
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    start = PAGE.index(open_tag) + len(open_tag)
    end = PAGE.index(close_tag, start)
    digest = hashlib.sha256(PAGE[start:end].encode()).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


CONTENT_SECURITY_POLICY = (
    f"default-src 'self'; script-src {_inline_hash('script')}; "
    f"style-src {_inline_hash('style')}; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _host_is_loopback(host_header: str | None) -> bool:
    """True when the request ``Host`` is a loopback name (or absent).

    The server binds 127.0.0.1, but DNS rebinding lets a remote page reach it through a
    victim's browser as a same-origin request. Rejecting a non-loopback ``Host`` blocks that
    while still allowing direct tools (which send a loopback Host or, for HTTP/1.0, none).
    """
    if not host_header:
        return True
    raw = host_header.strip().lower()
    if raw.startswith("["):  # bracketed IPv6, optional :port
        host = raw[1:].split("]", 1)[0]
    elif raw.count(":") == 1:  # host:port (a bare IPv6 has several colons)
        host = raw.rsplit(":", 1)[0]
    else:
        host = raw
    return host in _LOOPBACK_HOSTS


def _handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if not _host_is_loopback(self.headers.get("Host")):
                # Reject DNS-rebinding requests: a non-loopback Host means the request was
                # routed via a remote origin, not a local client on 127.0.0.1.
                self.send_error(403)
                return
            if self.path == "/":
                body = PAGE.encode()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/state":
                state = read_state(root)
                payload = {**state, "summary": summarize(state)}
                body = json.dumps(payload, sort_keys=True).encode()
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def create_server(root: Path, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), _handler(root))


def serve_ui(root: Path, port: int = 8765) -> None:
    server = create_server(root, port)
    host, bound_port = server.server_address
    print(f"looptight ui · http://{host}:{bound_port}")
    with server:
        server.serve_forever()
