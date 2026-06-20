"""Dependency-free, read-only localhost view of the latest swarm state."""

from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE_SCHEMA_VERSION = 1
STATE_FILE = "swarm-state.json"


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
    }


def write_state(root: Path, state: dict[str, object]) -> None:
    """Atomically publish state outside the tracked worktree."""
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_state(root: Path) -> dict[str, object]:
    path = _state_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA_VERSION:
        return empty_state()
    return payload


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
main{padding:28px 32px}.graph{position:relative;display:grid;grid-template-columns:minmax(180px,.7fr) minmax(240px,1fr) minmax(220px,1fr);gap:clamp(24px,5vw,90px);min-height:60vh;align-items:center}.lane{display:grid;gap:18px;position:relative;z-index:2}.lane-title{color:var(--muted);font-size:11px;letter-spacing:.2em;text-transform:uppercase}.node{position:relative;padding:18px;background:linear-gradient(135deg,#162019 0%,var(--panel) 70%);border:1px solid var(--line);border-left:4px solid var(--cyan);box-shadow:7px 7px 0 #050906}.node:focus{outline:2px solid var(--acid);outline-offset:4px}.node.manager{border-left-color:var(--acid);transform:skewY(-2deg)}.node.worker{border-left-color:var(--amber)}.node.failed,.node.error,.node.conflict{border-left-color:var(--red)}.eyebrow{color:var(--muted);font-size:10px;letter-spacing:.14em;text-transform:uppercase}.node h2{font:700 17px Georgia,serif;margin:5px 0 10px}.status{display:inline-block;color:#061006;background:var(--acid);padding:3px 7px;font-size:10px;font-weight:bold;text-transform:uppercase}.failed .status,.error .status,.conflict .status{background:var(--red)}.detail{color:var(--muted);font-size:12px;overflow-wrap:anywhere}.wires{position:absolute;inset:0;width:100%;height:100%;z-index:1;overflow:visible;pointer-events:none}.wire{stroke:var(--line);stroke-width:1.5;fill:none;marker-end:url(#arrow)}.empty{color:var(--muted);padding:18px;border:1px dashed var(--line)}footer{padding:16px 32px;color:var(--muted);border-top:1px solid var(--line);font-size:11px}
@media(max-width:760px){header{align-items:start;gap:20px}main{padding:24px 18px}.graph{grid-template-columns:1fr;gap:34px;align-items:start}.wires{display:none}}
@media(prefers-reduced-motion:no-preference){.live::before{animation:pulse 1.8s infinite}@keyframes pulse{50%{opacity:.35;box-shadow:0 0 3px var(--acid)}}}
</style>
</head>
<body>
<header><h1><span>LOOPTIGHT // LOCAL CONTROL</span>Swarm Signal</h1><div class="live" id="connection">connecting</div></header>
<main><section class="graph" id="graph" aria-label="Swarm orchestration graph"><svg class="wires" aria-hidden="true"><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#405047"/></marker></defs><g id="wires"></g></svg><div class="lane" id="manager"><div class="lane-title">manager</div></div><div class="lane" id="tasks"><div class="lane-title">tasks</div></div><div class="lane" id="workers"><div class="lane-title">workers</div></div></section></main>
<footer>READ ONLY · LOOPBACK INTERFACE · STATE SCHEMA <span id="schema">—</span></footer>
<script>
const $=id=>document.getElementById(id);
function node(kind,title,status,detail,id){const el=document.createElement('article');el.className=`node ${kind} ${status||''}`;el.tabIndex=0;el.dataset.node=id;el.setAttribute('aria-label',`${kind} ${title}, status ${status}`);for(const [cls,text] of [['eyebrow',kind],['title',title],['status',status],['detail',detail]]){const child=document.createElement(cls==='title'?'h2':'div');child.className=cls;child.textContent=text||'';el.append(child)}return el}
function fill(id,items,make){const lane=$(id);lane.querySelectorAll('.node,.empty').forEach(n=>n.remove());if(!items.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=`no ${id}`;lane.append(empty)}else items.forEach(item=>lane.append(make(item)))}
function wire(from,to){const a=document.querySelector(`[data-node="${CSS.escape(from)}"]`),b=document.querySelector(`[data-node="${CSS.escape(to)}"]`);if(!a||!b)return;const g=$('graph').getBoundingClientRect(),x1=a.getBoundingClientRect(),x2=b.getBoundingClientRect(),p=document.createElementNS('http://www.w3.org/2000/svg','path');const ax=x1.right-g.left,ay=x1.top+x1.height/2-g.top,bx=x2.left-g.left,by=x2.top+x2.height/2-g.top,m=(ax+bx)/2;p.setAttribute('d',`M${ax},${ay} C${m},${ay} ${m},${by} ${bx},${by}`);p.setAttribute('class','wire');$('wires').append(p)}
function render(s){const manager=s.manager||{status:'idle'};$('manager').querySelectorAll('.node').forEach(n=>n.remove());$('manager').append(node('manager','orchestrator',manager.status,'deterministic integration gate','manager'));fill('tasks',s.tasks||[],t=>node('task',t.goal||t.id,t.status,t.id,`task-${t.id}`));fill('workers',s.workers||[],w=>node('worker',`worker ${w.number}`,w.status,w.error||w.task_id||'',`worker-${w.number}`));$('schema').textContent=s.schema_version;$('wires').replaceChildren();(s.tasks||[]).forEach(t=>wire('manager',`task-${t.id}`));(s.workers||[]).forEach(w=>wire(`task-${w.task_id}`,`worker-${w.number}`))}
async function update(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error(r.status);render(await r.json());$('connection').textContent='live / polling'}catch(e){$('connection').textContent='state unavailable'}}
update();setInterval(update,1500);addEventListener('resize',()=>update());
</script>
</body></html>"""


def _handler(root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path == "/":
                body = PAGE.encode()
                content_type = "text/html; charset=utf-8"
            elif self.path == "/api/state":
                body = json.dumps(read_state(root), sort_keys=True).encode()
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
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
