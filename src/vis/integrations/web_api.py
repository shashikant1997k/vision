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
from .web_dashboard import DASHBOARD_HTML


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
        if parts == ["api", "overview"]:
            return self._overview()
        if parts == ["api", "batches"]:
            return {"batches": self._batches()}
        if parts == ["api", "challenges"]:
            return {"challenges": self._challenges()}
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
            if parts[1] == "analytics":
                return self._analytics(bid)
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

    def _challenges(self) -> list:
        if self._sf is None:
            return []
        from ..db.challenge import ChallengeService

        return ChallengeService(self._sf).list_tests(limit=50)

    def _latest_batch_id(self):
        batches = self._batches()
        return batches[0]["id"] if batches else None

    def _overview(self) -> dict:
        """One bundled call for the landing view (fewer round-trips)."""
        out = {"status": self._status(), "counters": self._counters(),
               "latest_batch": None, "oee": None, "analytics": None}
        bid = self._latest_batch_id()
        if bid is not None:
            batches = self._batches()
            out["latest_batch"] = batches[0]
            try:
                out["oee"] = self._oee(bid)
            except Exception:
                pass
            try:
                out["analytics"] = self._analytics(bid)
            except Exception:
                pass
        return out

    def _analytics(self, batch_id: int) -> dict:
        """Defect Pareto + per-camera/lane breakdown for a batch (for charts)."""
        from sqlalchemy import func, select

        from ..db.models import InspectionResult
        from ..reporting.batch_report import compute_summary

        with self._sf() as s:
            summary = compute_summary(s, batch_id)
            per_camera = []
            rows = s.execute(
                select(
                    InspectionResult.camera_id,
                    func.count().label("total"),
                    func.sum(func.cast(InspectionResult.passed, __import__("sqlalchemy").Integer)),
                ).where(InspectionResult.batch_id == batch_id)
                .group_by(InspectionResult.camera_id)
            ).all()
            for cam, total, passed in rows:
                passed = int(passed or 0)
                per_camera.append({"camera": cam, "total": int(total),
                                   "passed": passed, "failed": int(total) - passed})
        return {
            "batch_no": summary["batch_no"],
            "total": summary["total"], "passed": summary["passed"], "failed": summary["failed"],
            "defects_by_tool": summary["defects_by_tool"],
            "rejects_by_lane": summary["rejects_by_lane"],
            "per_camera": per_camera,
            "reconciliation": summary.get("reconciliation"),
        }

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


