from __future__ import annotations

from abc import ABC, abstractmethod
from threading import Lock


class RejectHandler(ABC):
    """Where a failed region is routed to its ejector.

    A production handler fires a digital output / PLC signal on the region's
    reject lane, applying the eject delay (inspection-to-ejector distance ÷
    conveyor speed, or an encoder count). That hardware piece lands with the
    reject-I/O driver; this interface keeps the runtime decoupled from it.
    """

    @abstractmethod
    def reject(self, region_result) -> None: ...


class RecordingRejectHandler(RejectHandler):
    """Records rejects in memory (placeholder for the digital-I/O ejector)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.rejects: list[tuple[str, str, str | None]] = []

    def reject(self, region_result) -> None:
        with self._lock:
            self.rejects.append(
                (region_result.camera_id, region_result.region_id, region_result.reject_output)
            )

    def count(self) -> int:
        with self._lock:
            return len(self.rejects)
