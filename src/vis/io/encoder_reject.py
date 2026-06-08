"""Encoder / pulse-based reject tracking (speed-independent ejection).

A time-delay ejector (eject after N ms) only works at a fixed line speed. The
industrial-standard approach tracks each rejected product by SHAFT-ENCODER
distance: when a product is rejected it's queued at the current encoder count,
and the ejector fires once the line has advanced exactly `eject_distance_pulses`
— correct at any speed, including stop/go. Encoder ticks come from the line
encoder input (the same signal that can trigger acquisition).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..runtime.reject import RejectHandler
from .digital_io import DigitalIO, SimulatedIO


@dataclass
class EncoderRejectConfig:
    name: str  # matches region.reject_output
    channel: int  # digital output channel for this ejector
    eject_distance_pulses: int  # encoder pulses from inspection point to ejector
    pulse_ms: int = 100  # ejector on-time


class EncoderRejectController(RejectHandler):
    """Routes rejects to ejectors by encoder distance (not a timer)."""

    def __init__(self, outputs, io: DigitalIO | None = None) -> None:
        self._outputs = {o.name: o for o in outputs}
        self.io = io or SimulatedIO()
        self._lock = threading.Lock()
        self._position = 0
        self._queue: list[tuple[int, int, int]] = []  # (fire_at_pos, channel, pulse_ms)
        self.fired = 0
        self.unmatched = 0

    def reject(self, region_result) -> None:
        cfg = self._outputs.get(region_result.reject_output)
        if cfg is None:
            with self._lock:
                self.unmatched += 1
            return
        with self._lock:
            self._queue.append(
                (self._position + cfg.eject_distance_pulses, cfg.channel, cfg.pulse_ms)
            )

    def tick(self, pulses: int = 1) -> None:
        """Advance the line by `pulses`; fire any ejectors whose product arrived."""
        with self._lock:
            self._position += pulses
            ready = [q for q in self._queue if q[0] <= self._position]
            self._queue = [q for q in self._queue if q[0] > self._position]
        for _pos, channel, pulse_ms in ready:
            self.io.pulse(channel, pulse_ms)
            with self._lock:
                self.fired += 1

    @property
    def position(self) -> int:
        with self._lock:
            return self._position

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def drain(self) -> None:
        """Fire all queued ejects (graceful shutdown of a bounded run)."""
        with self._lock:
            ready = list(self._queue)
            self._queue = []
        for _pos, channel, pulse_ms in ready:
            self.io.pulse(channel, pulse_ms)
            with self._lock:
                self.fired += 1

    def close(self) -> None:
        self.drain()
        self.io.close()
