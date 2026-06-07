from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from ..runtime.reject import RejectHandler
from .digital_io import DigitalIO, SimulatedIO


@dataclass
class RejectOutputConfig:
    """One reject lane / ejector."""

    name: str  # matches region.reject_output
    channel: int  # digital output channel
    eject_delay_ms: int = 0  # inspection-point -> ejector travel time
    pulse_ms: int = 100  # ejector on-time


class RejectController(RejectHandler):
    """Routes a rejected region to its lane's ejector.

    On a reject it waits the lane's eject delay (the time for the product to
    travel from the inspection point to the ejector) and then pulses the lane's
    digital output. Delayed ejects run on timers; `drain()` waits for any
    in-flight ejects (called on graceful shutdown). Pass a custom `scheduler`
    (e.g. immediate) for deterministic tests. Encoder-count timing is a later
    extension of the scheduler.
    """

    def __init__(
        self,
        outputs,
        io: DigitalIO | None = None,
        scheduler: Callable[[float, Callable[[], None]], None] | None = None,
    ) -> None:
        self._outputs = {o.name: o for o in outputs}
        self.io = io or SimulatedIO()
        self._scheduler = scheduler
        self._lock = threading.Lock()
        self._timers: list[threading.Timer] = []
        self.fired = 0
        self.unmatched = 0

    def _schedule(self, delay_s: float, fn: Callable[[], None]) -> None:
        if self._scheduler is not None:
            self._scheduler(delay_s, fn)
            return
        if delay_s <= 0:
            fn()
            return
        timer = threading.Timer(delay_s, fn)
        with self._lock:
            self._timers.append(timer)
        timer.start()

    def reject(self, region_result) -> None:
        cfg = self._outputs.get(region_result.reject_output)
        if cfg is None:
            with self._lock:
                self.unmatched += 1
            return

        def fire() -> None:
            self.io.pulse(cfg.channel, cfg.pulse_ms)
            with self._lock:
                self.fired += 1

        self._schedule(cfg.eject_delay_ms / 1000.0, fire)

    def drain(self, timeout: float = 2.0) -> None:
        with self._lock:
            timers = list(self._timers)
            self._timers = []
        for timer in timers:
            timer.join(timeout)

    def close(self) -> None:
        self.drain()
        self.io.close()
