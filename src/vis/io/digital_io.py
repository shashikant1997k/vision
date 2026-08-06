"""Digital outputs (ejector solenoids, beacons, buzzer) — the line-facing edge.

Safety position, and why this file is defensive: a vision system that stops
rejecting is more dangerous than one that stops running, because bad product
keeps shipping while every screen still looks green. So every write is
verified, comms faults are surfaced rather than swallowed, and the caller can
make loss of I/O stop the batch.

Timing division of labour (how Cognex/Keyence installations are wired): this PC
*decides*; deterministic hardware *actuates*. Pulse timing here is good to a few
milliseconds, which is right for ejector solenoids served from a queue, but a
high-speed line should let the encoder tracking (``encoder_reject``) or the PLC
own the exact moment of ejection.
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class IOFault(RuntimeError):
    """A digital output could not be driven — the line is no longer protected."""


class DigitalIO(ABC):
    """A set of digital outputs (e.g. ejector solenoids).

    Subclasses implement :meth:`write`. Pulses are served by ONE shared timer
    thread per instance (not a thread per pulse), so a fast line with many
    rejects cannot spawn unbounded threads, and a queued turn-off is not lost
    when a write raises.
    """

    def __init__(self) -> None:
        self._sched_lock = threading.Lock()
        self._sched: list[tuple[float, int, int]] = []   # (due, seq, channel)
        self._seq = 0
        self._wake = threading.Event()
        self._stop = False
        self._worker: threading.Thread | None = None

    @abstractmethod
    def write(self, channel: int, value: bool) -> None: ...

    @property
    def healthy(self) -> bool:
        """False when the link to the outputs is known to be broken."""
        return True

    def pulse(self, channel: int, ms: int) -> None:
        """Drive a channel high now and schedule it low after ``ms``."""
        self.write(channel, True)
        due = time.monotonic() + ms / 1000.0
        with self._sched_lock:
            self._seq += 1
            heapq.heappush(self._sched, (due, self._seq, channel))
            self._ensure_worker()
        self._wake.set()

    # ---- pulse scheduler -------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._stop = False
            self._worker = threading.Thread(
                target=self._run, name="digital-io-pulse", daemon=True
            )
            self._worker.start()

    def _run(self) -> None:
        while not self._stop:
            with self._sched_lock:
                due = self._sched[0][0] if self._sched else None
            if due is None:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            wait = due - time.monotonic()
            if wait > 0:
                self._wake.wait(min(wait, 0.5))
                self._wake.clear()
                continue
            with self._sched_lock:
                if not self._sched or self._sched[0][0] > time.monotonic():
                    continue
                _due, _seq, channel = heapq.heappop(self._sched)
            try:
                self.write(channel, False)
            except Exception:
                # never let one failed turn-off kill the scheduler; the fault is
                # reported through healthy/on_fault instead
                log.exception("failed to drop output channel %s", channel)

    def flush_pulses(self) -> None:
        """Drop every scheduled channel now (shutdown / e-stop)."""
        with self._sched_lock:
            pending, self._sched = self._sched, []
        for _due, _seq, channel in pending:
            try:
                self.write(channel, False)
            except Exception:
                log.exception("failed to drop output channel %s during flush", channel)

    def close(self) -> None:
        self._stop = True
        self._wake.set()
        self.flush_pulses()


class SimulatedIO(DigitalIO):
    """Records output activity in memory — for dev (macOS), tests, and the
    simulation source. ``pulse`` is recorded instantly (no real timer)."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.events: list[tuple[int, bool]] = []
        self._pulses: dict[int, int] = {}

    def write(self, channel: int, value: bool) -> None:
        with self._lock:
            self.events.append((channel, bool(value)))

    def pulse(self, channel: int, ms: int) -> None:
        with self._lock:
            self._pulses[channel] = self._pulses.get(channel, 0) + 1
            self.events.append((channel, True))
            self.events.append((channel, False))

    def pulse_count(self, channel: int) -> int:
        with self._lock:
            return self._pulses.get(channel, 0)


class ModbusTcpIO(DigitalIO):
    """Digital outputs over Modbus TCP (a remote I/O block such as a Moxa
    ioLogik, or a PLC coil area). Requires ``pip install '.[io]'``.

    Production behaviour:

    - every write is **checked** — pymodbus reports errors in the response
      object rather than raising, so an unchecked write silently does nothing;
    - a failed write is retried once after a reconnect (a dropped TCP session is
      the common, recoverable fault on a factory network);
    - if it still fails, :class:`IOFault` is raised and the link is marked
      unhealthy so the batch can be stopped instead of running unprotected;
    - access is serialised — a pymodbus client is not thread-safe and both the
      inspection thread and the pulse scheduler drive it;
    - ``on_fault(ok, detail)`` fires on each health transition for the HMI alarm.
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        unit: int = 1,
        *,
        connect_timeout: float = 3.0,
        on_fault=None,
        retry: bool = True,
        client=None,          # injectable for tests
    ) -> None:
        super().__init__()
        if client is None:
            try:
                from pymodbus.client import ModbusTcpClient
            except ImportError as exc:
                raise RuntimeError(
                    "pymodbus not installed. Install it with: pip install '.[io]'"
                ) from exc
            client = ModbusTcpClient(host, port=port, timeout=connect_timeout)
        self.host, self.port, self._unit = host, port, unit
        self._retry = retry
        self._on_fault = on_fault
        self._io_lock = threading.RLock()
        self._healthy = False
        self._client = client
        if not self._client.connect():
            raise IOFault(
                f"cannot connect to Modbus I/O at {host}:{port} — check the cable, "
                "the module's IP address, and that no other master holds the link."
            )
        self._healthy = True
        self.write_count = 0
        self.fault_count = 0
        self.last_write_ms = 0.0

    @property
    def healthy(self) -> bool:
        with self._io_lock:
            return self._healthy

    def _set_health(self, ok: bool, detail: str = "") -> None:
        with self._io_lock:
            changed = ok != self._healthy
            self._healthy = ok
        if changed:
            if ok:
                log.info("Modbus I/O %s:%s recovered", self.host, self.port)
            else:
                log.error("Modbus I/O %s:%s FAULT: %s", self.host, self.port, detail)
            if self._on_fault is not None:
                try:
                    self._on_fault(ok, detail)
                except Exception:
                    log.exception("I/O fault callback raised")

    def _write_once(self, channel: int, value: bool):
        result = self._client.write_coil(channel, bool(value), slave=self._unit)
        if result is None or (hasattr(result, "isError") and result.isError()):
            raise IOFault(f"Modbus write rejected for coil {channel}: {result!r}")
        return result

    def write(self, channel: int, value: bool) -> None:
        with self._io_lock:
            started = time.monotonic()
            try:
                self._write_once(channel, value)
            except Exception as first:
                if not self._retry:
                    self.fault_count += 1
                    self._set_health(False, str(first))
                    raise IOFault(str(first)) from first
                try:
                    self._client.close()
                    if not self._client.connect():
                        raise IOFault("reconnect failed")
                    self._write_once(channel, value)
                except Exception as second:
                    self.fault_count += 1
                    self._set_health(False, f"{first} (retry after reconnect: {second})")
                    raise IOFault(
                        f"output {channel} could not be driven — the line is NOT "
                        f"being protected. {second}"
                    ) from second
            self.write_count += 1
            self.last_write_ms = (time.monotonic() - started) * 1000.0
            self._set_health(True)

    def close(self) -> None:
        try:
            super().close()          # drop scheduled pulses first
        finally:
            with self._io_lock:
                self._client.close()
                self._healthy = False
