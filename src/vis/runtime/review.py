"""Failed-image review buffer.

Keeps the most recent rejected frames (image + results) so an operator can step
through them and see exactly why each product was rejected — a staple of every
industrial vision HMI (Cognex EasyBuilder filmstrip, etc.). Thread-safe ring
buffer: acquisition threads append, the HMI reads.
"""

from __future__ import annotations

from collections import deque
from threading import Lock


class FailedImageLog:
    def __init__(self, capacity: int = 50) -> None:
        self._lock = Lock()
        self._items: deque = deque(maxlen=capacity)

    def add(self, frame, results) -> None:
        """Store a rejected frame. Only call when at least one region failed."""
        with self._lock:
            self._items.append(
                {
                    "frame_id": frame.frame_id,
                    "camera_id": frame.camera_id,
                    "image": frame.image,
                    "results": list(results),
                }
            )

    def items(self) -> list:
        with self._lock:
            return list(self._items)

    def latest(self):
        with self._lock:
            return self._items[-1] if self._items else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
