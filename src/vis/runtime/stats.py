from __future__ import annotations

import copy
from threading import Lock


class LiveStats:
    """Thread-safe running counters, per camera and in total. Cameras update
    concurrently from their acquisition threads; the HMI reads snapshots."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._per_camera: dict[str, dict] = {}
        self._cycle_last = 0.0
        self._cycle_avg = 0.0  # exponential moving average (ms)

    def record_cycle(self, ms: float) -> None:
        """Record one inspection cycle time (ms) — drives the live readout that
        tells the operator the line is keeping up with the trigger rate."""
        with self._lock:
            self._cycle_last = float(ms)
            self._cycle_avg = ms if self._cycle_avg == 0.0 else 0.8 * self._cycle_avg + 0.2 * ms

    def cycle_ms(self) -> dict[str, float]:
        with self._lock:
            return {"last": round(self._cycle_last, 1), "avg": round(self._cycle_avg, 1)}

    def record(self, region_result) -> None:
        with self._lock:
            cam = self._per_camera.setdefault(
                region_result.camera_id,
                {"total": 0, "passed": 0, "failed": 0, "rejects_by_lane": {}, "rejects_by_reason": {}},
            )
            cam.setdefault("rejects_by_reason", {})
            cam["total"] += 1
            # per-lane running counts + the latest result (drives the live ✓/✗)
            lane_name = region_result.reject_output or "?"
            lanes = cam.setdefault("lanes", {})
            lane = lanes.setdefault(lane_name, {"total": 0, "passed": 0, "failed": 0, "last": None})
            lane["total"] += 1
            lane["passed" if region_result.passed else "failed"] += 1
            lane["last"] = bool(region_result.passed)
            if region_result.passed:
                cam["passed"] += 1
                cam["consecutive_failed"] = 0
            else:
                cam["consecutive_failed"] = cam.get("consecutive_failed", 0) + 1
                cam["failed"] += 1
                lane = region_result.reject_output or "?"
                cam["rejects_by_lane"][lane] = cam["rejects_by_lane"].get(lane, 0) + 1
                for tr in region_result.tool_results:  # which inspection(s) failed
                    if not tr.passed:
                        cam["rejects_by_reason"][tr.tool_id] = (
                            cam["rejects_by_reason"].get(tr.tool_id, 0) + 1
                        )

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
            out["yield"] = (100.0 * out["passed"] / out["total"]) if out["total"] else 0.0
            return out

    def reset_consecutive(self) -> None:
        """Clear the consecutive-reject streak on all cameras — used when the
        operator acknowledges a line-stop alarm so a restart doesn't re-trip it."""
        with self._lock:
            for cam in self._per_camera.values():
                cam["consecutive_failed"] = 0

    def consecutive_failures(self) -> int:
        """The worst current run of consecutive rejects across cameras — drives
        the line-stop alarm (a failed coder rejects everything; the line must
        stop, not keep ejecting)."""
        with self._lock:
            return max(
                (cam.get("consecutive_failed", 0) for cam in self._per_camera.values()),
                default=0,
            )

    def reject_reasons(self) -> dict[str, int]:
        """Aggregated reject counts by failing inspection, across all cameras."""
        with self._lock:
            out: dict[str, int] = {}
            for cam in self._per_camera.values():
                for reason, n in cam.get("rejects_by_reason", {}).items():
                    out[reason] = out.get(reason, 0) + n
            return dict(sorted(out.items(), key=lambda kv: -kv[1]))
