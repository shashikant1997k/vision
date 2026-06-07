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


def _timer_scheduler(delay_s: float, fn: Callable[[], None]) -> None:
    if delay_s <= 0:
        fn()
    else:
        threading.Timer(delay_s, fn).start()


class RejectController(RejectHandler):
    """Routes a rejected region to its lane's ejector.

    On a reject it waits the lane's eject delay (the time for the product to
    travel from the inspection point to the ejector) and then pulses the lane's
    digital output. Multiple rejects can be in flight per lane. Encoder-based
    timing (fire after N encoder counts) is a later extension of the scheduler.
    """

    def __init__(
        self,
        outputs,
        io: DigitalIO | None = None,
        scheduler: Callable[[float, Callable[[], None]], None] = _timer_scheduler,
    ) -> None:
        self._outputs = {o.name: o for o in outputs}
        self.io = io or SimulatedIO()
        self._scheduler = scheduler
        self._lock = threading.Lock()
        self.fired = 0
        self.unmatched = 0

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

        self._scheduler(cfg.eject_delay_ms / 1000.0, fire)

    def close(self) -> None:
        self.io.close()
