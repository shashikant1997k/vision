"""24 V hard-wired line signals (docs/12-integration-protocol.md §2).

Drives the discrete outputs a PLC/line-master watches: READY, RUNNING, PASS
pulse, REJECT pulse, latched ALARM, and a HEARTBEAT toggle (watchdog). Sits on
any DigitalIO backend (SimulatedIO in dev, ModbusTcpIO on the line) and
subscribes to the EventBus for per-product pulses.

    signals = LineSignals(io, SignalMap(ready=1, running=2, pass_pulse=3,
                                        reject_pulse=4, alarm=5, heartbeat=6))
    bus.subscribe("inspection.result", signals.on_result)
    signals.set_ready(True); signals.set_running(True)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .digital_io import DigitalIO, SimulatedIO


@dataclass
class SignalMap:
    """Output channel numbers (0 = not wired)."""

    ready: int = 0
    running: int = 0
    pass_pulse: int = 0
    reject_pulse: int = 0
    alarm: int = 0
    heartbeat: int = 0
    conveyor: int = 0  # conveyor run output (operator CONVEYOR ON/OFF)
    pass_pulse_ms: int = 50
    reject_pulse_ms: int = 100
    heartbeat_ms: int = 500

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in (
            "ready", "running", "pass_pulse", "reject_pulse", "alarm",
            "heartbeat", "conveyor", "pass_pulse_ms", "reject_pulse_ms", "heartbeat_ms",
        )}

    @classmethod
    def from_dict(cls, d: dict | None) -> SignalMap:
        d = d or {}
        return cls(**{k: int(d.get(k, getattr(cls, k, 0) if not k.endswith("_ms") else
                                  {"pass_pulse_ms": 50, "reject_pulse_ms": 100, "heartbeat_ms": 500}[k]))
                      for k in cls().to_dict()})


class LineSignals:
    """State + pulse driver for the hard-wired interface. Fail-safe: READY and
    RUNNING drop on close(); ALARM is latched until reset_alarm()."""

    def __init__(self, io: DigitalIO | None = None, mapping: SignalMap | None = None) -> None:
        self.io = io or SimulatedIO()
        self.map = mapping or SignalMap()
        self._lock = threading.Lock()
        self._alarm = False
        self._beat_state = False
        self._beat_timer: threading.Timer | None = None

    # ---- levels -------------------------------------------------------------
    def _write(self, channel: int, value: bool) -> None:
        if channel:
            self.io.write(channel, value)

    def set_ready(self, ready: bool) -> None:
        self._write(self.map.ready, ready)

    def set_running(self, running: bool) -> None:
        self._write(self.map.running, running)

    def set_conveyor(self, on: bool) -> None:
        self._write(self.map.conveyor, on)

    def set_alarm(self, alarm: bool) -> None:
        with self._lock:
            self._alarm = alarm
        self._write(self.map.alarm, alarm)

    def reset_alarm(self) -> None:
        self.set_alarm(False)

    @property
    def alarm(self) -> bool:
        with self._lock:
            return self._alarm

    # ---- per-product pulses ---------------------------------------------------
    def on_result(self, region_result) -> None:
        """EventBus hook: pulse PASS or REJECT for each product."""
        if region_result.passed:
            if self.map.pass_pulse:
                self.io.pulse(self.map.pass_pulse, self.map.pass_pulse_ms)
        elif self.map.reject_pulse:
            self.io.pulse(self.map.reject_pulse, self.map.reject_pulse_ms)

    # ---- heartbeat (PLC watchdog) ---------------------------------------------
    def start_heartbeat(self) -> None:
        if not self.map.heartbeat:
            return
        self.stop_heartbeat()
        self._beat()

    def _beat(self) -> None:
        self._beat_state = not self._beat_state
        self._write(self.map.heartbeat, self._beat_state)
        self._beat_timer = threading.Timer(self.map.heartbeat_ms / 1000.0, self._beat)
        self._beat_timer.daemon = True
        self._beat_timer.start()

    def stop_heartbeat(self) -> None:
        if self._beat_timer is not None:
            self._beat_timer.cancel()
            self._beat_timer = None

    def close(self) -> None:
        """Fail-safe shutdown: drop READY/RUNNING, stop the heartbeat."""
        self.stop_heartbeat()
        self.set_running(False)
        self.set_ready(False)
