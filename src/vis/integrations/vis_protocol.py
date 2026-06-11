"""VIS Integration Protocol v1 server (docs/12-integration-protocol.md).

JSON-Lines over TCP: pushes results/alarms/state/heartbeats to every connected
client and answers commands (hello/get_status/get_counters/list_recipes/start/
stop/ping) with ok/error replies. Wire it to the EventBus and the HMI:

    server = VisProtocolServer(port=9410, callbacks={...})
    bus.subscribe("inspection.result", server.on_result)
    server.start()

Threaded, multi-client, non-blocking for the inspection path (a slow client is
disconnected rather than ever stalling the line).
"""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime, timezone

PROTO = "VIS/1"
ERR_BAD_JSON = "BAD_JSON"
ERR_UNKNOWN = "UNKNOWN_CMD"
ERR_NOT_ALLOWED = "NOT_ALLOWED"
ERR_INTERNAL = "INTERNAL"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _disp(value) -> str:
    return "" if value is None else str(value).replace("\x1d", "<GS>")


def result_message(region_result, batch_no: str | None = None) -> dict:
    """Serialize a RegionResult into the protocol's `result` push."""
    fields = []
    for tr in region_result.tool_results:
        field = {
            "id": tr.tool_id,
            "passed": bool(tr.passed),
            "value": _disp(tr.measured_value),
        }
        if tr.expected_value:
            field["expected"] = _disp(tr.expected_value)
        if tr.confidence:
            field["confidence"] = round(float(tr.confidence), 3)
        grade = (tr.detail or {}).get("grade", {}).get("overall")
        if grade:
            field["grade"] = grade
        fields.append(field)
    return {
        "type": "result",
        "ts": _now(),
        "camera": region_result.camera_id,
        "frame": region_result.frame_id,
        "product": region_result.region_id,
        "passed": bool(region_result.passed),
        "lane": region_result.reject_output,
        "batch": batch_no,
        "fields": fields,
    }


class VisProtocolServer:
    """Multi-client JSON-Lines TCP server for third-party integration."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9410,
        callbacks: dict | None = None,
        heartbeat_s: float = 5.0,
        send_timeout_s: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.callbacks = callbacks or {}
        self.heartbeat_s = heartbeat_s
        self.send_timeout_s = send_timeout_s
        self.batch_no: str | None = None
        self._sock: socket.socket | None = None
        self._clients: dict[socket.socket, threading.Lock] = {}
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> VisProtocolServer:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self.port = self._sock.getsockname()[1]  # resolve port 0
        self._sock.listen(8)
        self._sock.settimeout(0.5)
        accept = threading.Thread(target=self._accept_loop, daemon=True, name="vis-proto-accept")
        accept.start()
        beat = threading.Thread(target=self._heartbeat_loop, daemon=True, name="vis-proto-beat")
        beat.start()
        self._threads = [accept, beat]
        return self

    def stop(self) -> None:
        self._stop.set()
        for client in list(self._clients):
            self._drop(client)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ---- pushes ------------------------------------------------------------
    def on_result(self, region_result) -> None:
        """EventBus hook: push a result to every client (never blocks the line)."""
        self._broadcast(result_message(region_result, self.batch_no))

    def push_alarm(self, code: str, message: str) -> None:
        self._broadcast({"type": "alarm", "ts": _now(), "code": code, "message": message})

    def push_state(self, running: bool, batch: str | None = None) -> None:
        self.batch_no = batch
        self._broadcast({"type": "state", "running": bool(running), "batch": batch})

    def _broadcast(self, message: dict) -> None:
        with self._lock:
            self._seq += 1
            message = {**message, "seq": self._seq}
            clients = list(self._clients.items())
        data = (json.dumps(message) + "\n").encode()
        for client, lock in clients:
            try:
                with lock:
                    client.settimeout(self.send_timeout_s)
                    client.sendall(data)
            except OSError:
                self._drop(client)  # a slow/dead client never stalls the line

    # ---- command handling ----------------------------------------------------
    def _handle(self, request: dict) -> dict:
        cmd = request.get("cmd")
        rid = request.get("id")
        reply: dict = {"ok": True, "id": rid}
        try:
            if cmd == "hello":
                reply.update(proto=PROTO, app="vision-inspection")
            elif cmd == "ping":
                reply.update(pong=True)
            elif cmd == "get_status":
                status = self._call("get_status") or {}
                reply.update(status)
            elif cmd == "get_counters":
                counters = self._call("get_counters") or {}
                reply.update(counters)
            elif cmd == "list_recipes":
                reply.update(recipes=self._call("list_recipes") or [])
            elif cmd in ("start", "stop"):
                handler = self.callbacks.get(cmd)
                if handler is None:
                    return {"ok": False, "id": rid, "error": ERR_NOT_ALLOWED,
                            "message": f"{cmd} is not enabled for remote clients"}
                handler()
            else:
                return {"ok": False, "id": rid, "error": ERR_UNKNOWN,
                        "message": f"unknown cmd {cmd!r}"}
        except Exception as exc:  # a handler bug must not kill the connection
            return {"ok": False, "id": rid, "error": ERR_INTERNAL, "message": str(exc)}
        return reply

    def _call(self, name: str):
        handler = self.callbacks.get(name)
        return handler() if handler else None

    # ---- socket plumbing -----------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set() and self._sock is not None:
            try:
                client, _addr = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                self._clients[client] = threading.Lock()
            self._send(client, {"type": "hello", "proto": PROTO, "app": "vision-inspection"})
            reader = threading.Thread(
                target=self._client_loop, args=(client,), daemon=True, name="vis-proto-client"
            )
            reader.start()

    def _client_loop(self, client: socket.socket) -> None:
        buffer = b""
        client.settimeout(0.5)
        while not self._stop.is_set():
            try:
                chunk = client.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    self._send(client, {"ok": False, "error": ERR_BAD_JSON,
                                        "message": "each message must be one JSON object per line"})
                    continue
                self._send(client, self._handle(request))
        self._drop(client)

    def _send(self, client: socket.socket, message: dict) -> None:
        with self._lock:
            self._seq += 1
            lock = self._clients.get(client)
        if lock is None:
            return
        try:
            with lock:
                client.settimeout(self.send_timeout_s)
                client.sendall((json.dumps({**message, "seq": self._seq}) + "\n").encode())
        except OSError:
            self._drop(client)

    def _drop(self, client: socket.socket) -> None:
        with self._lock:
            self._clients.pop(client, None)
        try:
            client.close()
        except OSError:
            pass

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.heartbeat_s)
            if self._clients:
                self._broadcast({"type": "heartbeat", "ts": _now()})
