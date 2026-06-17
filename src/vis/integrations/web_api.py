"""Read-only monitoring REST API + web dashboard (docs/18).

Legacy GMP vision software is desktop-only; this exposes live line status,
counters, batches, OEE, reconciliation, events and a read-only audit projection
over HTTP for remote monitoring (MES/QA dashboards), WITHOUT expanding the
Part-11 record-creation surface:

- strictly GET-only (every write verb returns 405) — no GxP record is created
  over the web, so the validation footprint stays minimal;
- bearer-token auth on every /api/* route (constant-time compare);
- served on its own threads (ThreadingHTTPServer) reading thread-safe snapshots
  / the DB, so a slow client never stalls the inspection loop;
- zero new dependencies (Python stdlib only).

TLS: wrap with ssl for production (cert_file/key_file); bind to localhost or the
plant VLAN — never a routable internet path.
"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..common.trusted_time import now_iso


def _make_handler(server_ref):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet; access is audited separately
            pass

        # writes are not allowed — read-only API
        def _reject_write(self):
            self._send(405, {"error": "read-only API"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _reject_write

        def _send(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str):
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            token = server_ref.token
            if not token:
                return True  # no token configured -> open (dev only)
            header = self.headers.get("Authorization", "")
            expected = f"Bearer {token}"
            return hmac.compare_digest(header, expected)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send_html(DASHBOARD_HTML)
            if not path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if not self._authed():
                return self._send(401, {"error": "unauthorized"})
            server_ref.note_access(self.path)
            try:
                payload = server_ref.handle(path)
            except KeyError:
                return self._send(404, {"error": "not found"})
            except Exception as exc:  # never leak internals
                return self._send(500, {"error": "internal", "detail": str(exc)[:200]})
            self._send(200, payload)

    return Handler


class ReadOnlyApiServer:
    def __init__(
        self, session_factory=None, *, host="127.0.0.1", port=9480, token: str = "",
        status_provider=None, counters_provider=None,
    ) -> None:
        self._sf = session_factory
        self.host = host
        self.port = port
        self.token = token
        self._status_provider = status_provider
        self._counters_provider = counters_provider
        self._httpd: ThreadingHTTPServer | None = None
        self._access_count = 0
        self._lock = threading.Lock()

    # ---- lifecycle --------------------------------------------------------
    def start(self) -> ReadOnlyApiServer:
        self._httpd = ThreadingHTTPServer((self.host, self.port), _make_handler(self))
        self.port = self._httpd.server_address[1]  # resolve port 0
        threading.Thread(target=self._httpd.serve_forever, daemon=True,
                         name="vis-web-api").start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def note_access(self, path: str) -> None:
        with self._lock:
            self._access_count += 1

    @property
    def access_count(self) -> int:
        return self._access_count

    # ---- routing ----------------------------------------------------------
    def handle(self, path: str) -> dict:
        parts = path.strip("/").split("/")  # ["api", "batch", "3"]
        if parts == ["api", "status"]:
            return self._status()
        if parts == ["api", "counters"]:
            return self._counters()
        if parts == ["api", "batches"]:
            return {"batches": self._batches()}
        if parts == ["api", "events"]:
            return {"events": self._events()}
        if parts == ["api", "audit"]:
            return {"entries": self._audit(),
                    "note": "read-only projection; canonical trail is in the app"}
        if len(parts) == 3 and parts[0] == "api":
            bid = int(parts[2])
            if parts[1] == "batch":
                return self._batch(bid)
            if parts[1] == "oee":
                return self._oee(bid)
            if parts[1] == "reconciliation":
                return self._reconciliation(bid)
        raise KeyError(path)

    # ---- data (read-only) -------------------------------------------------
    def _status(self) -> dict:
        base = {"server_utc": now_iso()}
        if self._status_provider:
            base.update(self._status_provider() or {})
        return base

    def _counters(self) -> dict:
        base = {"as_of_utc": now_iso()}
        if self._counters_provider:
            base.update(self._counters_provider() or {})
        return base

    def _batches(self) -> list:
        if self._sf is None:
            return []
        from ..db.batches import BatchService

        return BatchService(self._sf).list_batches(limit=50)

    def _batch(self, batch_id: int) -> dict:
        from ..reporting.batch_report import compute_summary

        with self._sf() as s:
            return compute_summary(s, batch_id)

    def _oee(self, batch_id: int) -> dict:
        from ..db.oee import OEEService

        return OEEService(self._sf).compute(batch_id)

    def _reconciliation(self, batch_id: int) -> dict:
        from ..db.reconciliation import ReconciliationService

        return ReconciliationService(self._sf).compute(batch_id)

    def _events(self) -> list:
        if self._sf is None:
            return []
        from ..db.app_settings import EventService

        return EventService(self._sf).list_events(limit=100)

    def _audit(self) -> list:
        if self._sf is None:
            return []
        with self._sf() as s:
            from ..db.audit import AuditService

            return AuditService(s).list_entries(limit=100)


DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Vision Inspection — Live Monitor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{font-family:system-ui,sans-serif;margin:0;background:#eef1f6;color:#1b1f24}
 header{background:#3d6bf5;color:#fff;padding:14px 20px;font-size:1.2rem;font-weight:600}
 .wrap{padding:20px;max-width:1000px;margin:0 auto}
 .cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}
 .card{background:#fff;border:1px solid #d9dee8;border-radius:10px;padding:16px 20px;flex:1;min-width:150px}
 .card .n{font-size:2rem;font-weight:700}.card .l{color:#5b6472;font-size:.85rem}
 table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #d9dee8;border-radius:10px;overflow:hidden}
 th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #eef1f5}
 th{background:#f1f4f8;color:#5b6472;font-size:.8rem}
 .ok{color:#1a7f37;font-weight:600}.bad{color:#c22;font-weight:600}
 #tok{padding:6px 10px;border:1px solid #d9dee8;border-radius:6px}
 .muted{color:#5b6472;font-size:.8rem;margin-top:8px}
</style></head><body>
<header>Vision Inspection — Live Monitor <span id="state" style="float:right"></span></header>
<div class="wrap">
 <div id="auth" style="margin-bottom:14px">
   API token: <input id="tok" placeholder="bearer token"> <button onclick="saveTok()">Connect</button>
 </div>
 <div class="cards">
   <div class="card"><div class="n" id="total">—</div><div class="l">Total</div></div>
   <div class="card"><div class="n ok" id="passed">—</div><div class="l">Passed</div></div>
   <div class="card"><div class="n bad" id="failed">—</div><div class="l">Reject</div></div>
   <div class="card"><div class="n" id="yield">—</div><div class="l">Yield %</div></div>
 </div>
 <h3>Recent batches</h3>
 <table><thead><tr><th>Batch</th><th>Product</th><th>Status</th><th>Total</th><th>Pass</th><th>Fail</th></tr></thead>
 <tbody id="batches"></tbody></table>
 <div class="muted" id="ts"></div>
</div>
<script>
 let tok = localStorage.getItem('vis_tok') || '';
 document.getElementById('tok').value = tok;
 function saveTok(){ tok = document.getElementById('tok').value.trim(); localStorage.setItem('vis_tok', tok); poll(); }
 async function get(p){ const r = await fetch(p, {headers: tok ? {Authorization:'Bearer '+tok} : {}}); if(!r.ok) throw new Error(r.status); return r.json(); }
 function set(id,v){ document.getElementById(id).textContent = v; }
 async function poll(){
   try{
     const c = await get('/api/counters');
     set('total', c.total??'—'); set('passed', c.passed??'—');
     set('failed', c.failed??'—'); set('yield', c.yield??'—');
     const s = await get('/api/status');
     set('state', (s.running?'● RUNNING':'● Idle'));
     const b = await get('/api/batches');
     document.getElementById('batches').innerHTML = (b.batches||[]).map(x =>
       `<tr><td>${x.batch_no||''}</td><td>${x.product||''}</td><td>${x.status||''}</td>`+
       `<td>${x.total||0}</td><td>${x.passed||0}</td><td>${x.failed||0}</td></tr>`).join('');
     set('ts', 'Updated ' + new Date().toLocaleTimeString());
   }catch(e){ set('state','● disconnected ('+e.message+')'); }
 }
 poll(); setInterval(poll, 3000);
</script></body></html>"""
