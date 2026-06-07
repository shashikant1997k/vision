from __future__ import annotations

import copy
from threading import Lock


class LiveStats:
    """Thread-safe running counters, per camera and in total. Cameras update
    concurrently from their acquisition threads; the HMI reads snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._per_camera: dict[str, dict] = {}

    def record(self, region_result) -> None:
        with self._lock:
            cam = self._per_camera.setdefault(
                region_result.camera_id,
                {"total": 0, "passed": 0, "failed": 0, "rejects_by_lane": {}},
            )
            cam["total"] += 1
            if region_result.passed:
                cam["passed"] += 1
            else:
                cam["failed"] += 1
                lane = region_result.reject_output or "?"
                cam["rejects_by_lane"][lane] = cam["rejects_by_lane"].get(lane, 0) + 1

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return copy.deepcopy(self._per_camera)

    def totals(self) -> dict[str, int]:
        with self._lock:
            out = {"total": 0, "passed": 0, "failed": 0}
            for cam in self._per_camera.values():
                out["total"] += cam["total"]
                out["passed"] += cam["passed"]
                out["failed"] += cam["failed"]
            return out
