"""Trusted time — ALCOA+ "Contemporaneous" control (docs/17).

Regulators (MHRA / PIC-S PI 041 / 21 CFR 11.10(e) / Annex 11) expect a
synchronised time source, timestamps stored unambiguously (UTC + offset), and
DETECTION + recording of any clock change. A user-space app can't prevent a
clock change without OS controls, but it can detect and record it:

1. monotonic-vs-wall skew: time.monotonic() is immune to clock changes,
   time.time() is not — a divergence between their deltas is a clock jump
   (a BACKWARD jump is the classic backdating pattern → critical).
2. optional NTP offset check (when ntplib + a server are available): flag drift
   beyond tolerance / bad stratum / unreachable.

Anomalies are written as a `time.anomaly` audit entry (classified CRITICAL by
the audit-review taxonomy) plus an operational event.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

JUMP_TOLERANCE_S = 2.0   # allowed |wall - mono| step per tick (NTP slew / jitter)
NTP_WARN_S = 1.0
NTP_FAIL_S = 2.0
NTP_MAX_STRATUM = 4


def now_iso() -> str:
    """Canonical timestamp: timezone-aware UTC in ISO 8601 (…+00:00). Never a
    naive local timestamp (which is a data-integrity finding)."""
    return datetime.now(timezone.utc).isoformat()


def detect_clock_jump(
    prev_mono: float, prev_wall: float, mono: float, wall: float,
    tolerance: float = JUMP_TOLERANCE_S,
) -> dict | None:
    """Compare elapsed monotonic vs wall time. Returns an anomaly dict when the
    wall clock stepped relative to true elapsed time, else None."""
    mono_delta = mono - prev_mono
    wall_delta = wall - prev_wall
    skew = wall_delta - mono_delta  # +ve = clock jumped forward, -ve = backward
    if abs(skew) <= tolerance:
        return None
    return {
        "kind": "CLOCK_JUMP",
        "severity": "critical",
        "direction": "forward" if skew > 0 else "backward",
        "magnitude_s": round(skew, 3),
        "wall_before": datetime.fromtimestamp(prev_wall, timezone.utc).isoformat(),
        "wall_after": datetime.fromtimestamp(wall, timezone.utc).isoformat(),
        "detector": "monotonic_vs_wall",
    }


def check_ntp_offset(server: str, warn: float = NTP_WARN_S, fail: float = NTP_FAIL_S) -> dict | None:
    """Query an NTP server and flag drift / bad stratum / unreachable. Returns
    an anomaly dict or None. No-op (returns None) if ntplib is not installed."""
    try:
        import ntplib
    except ImportError:
        return None
    try:
        response = ntplib.NTPClient().request(server, version=3, timeout=5)
    except Exception as exc:  # unreachable / timeout
        return {"kind": "NTP_UNREACHABLE", "severity": "major",
                "server": server, "detail": str(exc), "detector": "ntp"}
    if response.stratum == 0 or response.stratum > NTP_MAX_STRATUM:
        return {"kind": "NTP_BAD_STRATUM", "severity": "major",
                "server": server, "stratum": response.stratum, "detector": "ntp"}
    offset = response.offset
    if abs(offset) > fail:
        return {"kind": "NTP_DRIFT", "severity": "critical", "server": server,
                "offset_s": round(offset, 3), "stratum": response.stratum, "detector": "ntp"}
    if abs(offset) > warn:
        return {"kind": "NTP_DRIFT", "severity": "major", "server": server,
                "offset_s": round(offset, 3), "stratum": response.stratum, "detector": "ntp"}
    return None


def record_time_anomaly(session_factory, anomaly: dict, ntp_server: str | None = None) -> None:
    """Persist a time anomaly as a `time.anomaly` audit entry + an alarm event."""
    from ..db.app_settings import EventService
    from ..db.audit import AuditService

    detail = {**anomaly, "recorded_utc": now_iso()}
    with session_factory() as s:
        AuditService(s).record("time.anomaly", "system", ntp_server or "clock", after=detail)
        s.commit()
    message = (
        f"Time anomaly: {anomaly.get('kind')} "
        f"{anomaly.get('direction', '')} {anomaly.get('magnitude_s', anomaly.get('offset_s', ''))}s"
    ).strip()
    EventService(session_factory).log("alarm", "time", message)


class TimeMonitor:
    """Background clock-tamper + NTP-drift monitor. on_anomaly(dict) is called
    from the monitor thread for each anomaly (never blocks the line). Drive it in
    tests by calling check_skew()/check_ntp() directly."""

    def __init__(
        self, on_anomaly, *, tick_s: float = 5.0, tolerance: float = JUMP_TOLERANCE_S,
        ntp_server: str | None = None, ntp_interval_s: float = 300.0,
        mono_fn=time.monotonic, wall_fn=time.time,
    ) -> None:
        self._on_anomaly = on_anomaly
        self._tick = tick_s
        self._tolerance = tolerance
        self._ntp_server = ntp_server
        self._ntp_interval = ntp_interval_s
        self._mono_fn = mono_fn
        self._wall_fn = wall_fn
        self._prev_mono = mono_fn()
        self._prev_wall = wall_fn()
        self._last_ntp = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_skew(self) -> dict | None:
        mono, wall = self._mono_fn(), self._wall_fn()
        anomaly = detect_clock_jump(self._prev_mono, self._prev_wall, mono, wall, self._tolerance)
        self._prev_mono, self._prev_wall = mono, wall
        if anomaly:
            self._on_anomaly(anomaly)
        return anomaly

    def check_ntp(self) -> dict | None:
        if not self._ntp_server:
            return None
        anomaly = check_ntp_offset(self._ntp_server)
        if anomaly:
            self._on_anomaly(anomaly)
        return anomaly

    def start(self) -> TimeMonitor:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vis-time-monitor")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._tick):
            try:
                self.check_skew()
                now = self._mono_fn()
                if self._ntp_server and (now - self._last_ntp) >= self._ntp_interval:
                    self._last_ntp = now
                    self.check_ntp()
            except Exception:
                pass  # the monitor must never crash the line
