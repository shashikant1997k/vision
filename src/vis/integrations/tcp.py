from __future__ import annotations

import socket
import threading


class TcpResultServer:
    """TCP server transport: third-party apps connect to us and receive the
    stream of result messages. Broadcasts each published message to all
    connected clients; drops clients that have disconnected.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 0) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen()
        self.host, self.port = self._srv.getsockname()
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            with self._lock:
                self._clients.append(conn)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def publish(self, message: str) -> None:
        data = message.encode("utf-8")
        with self._lock:
            dead = []
            for c in self._clients:
                try:
                    c.sendall(data)
                except OSError:
                    dead.append(c)
            for c in dead:
                self._clients.remove(c)

    def close(self) -> None:
        self._running = False
        try:
            self._srv.close()
        except OSError:
            pass
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except OSError:
                    pass
            self._clients.clear()


class TcpResultClient:
    """TCP client transport: we connect out to a third-party host:port and push
    messages. Store-and-forward — messages are buffered (bounded) and flushed on
    reconnect, so data survives short peer outages.
    """

    def __init__(self, host: str, port: int, buffer_limit: int = 1000) -> None:
        self.host = host
        self.port = port
        self._buffer_limit = buffer_limit
        self._sock: socket.socket | None = None
        self._buf: list[bytes] = []
        self._lock = threading.Lock()

    def _ensure_connected(self) -> None:
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=2.0)

    def _drop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def publish(self, message: str) -> None:
        with self._lock:
            self._buf.append(message.encode("utf-8"))
            if len(self._buf) > self._buffer_limit:
                self._buf = self._buf[-self._buffer_limit :]  # bound store-and-forward
            try:
                self._ensure_connected()
                while self._buf:
                    self._sock.sendall(self._buf[0])  # type: ignore[union-attr]
                    self._buf.pop(0)
            except OSError:
                self._drop()  # keep buffered; retry on next publish

    def close(self) -> None:
        with self._lock:
            self._drop()
