from __future__ import annotations

from threading import Lock


class LiveView:
    """Holds the latest (frame, results) per camera for display by the HMI.

    The acquisition threads write; the UI reads the most recent snapshot. Only
    the latest is kept (display doesn't need history)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._latest: dict[str, tuple] = {}

    def update(self, frame, results) -> None:
        with self._lock:
            if not results:
                # a fresh frame pushed BEFORE inspection (for smooth live video):
                # keep the last real verdict so the on-screen PASS/FAIL doesn't
                # flicker to PASS during the read window — only the image advances
                prev = self._latest.get(frame.camera_id)
                if prev is not None:
                    results = prev[1]
            self._latest[frame.camera_id] = (frame, results)

    def latest(self, camera_id: str):
        with self._lock:
            return self._latest.get(camera_id)

    def camera_ids(self) -> list[str]:
        with self._lock:
            return list(self._latest)
