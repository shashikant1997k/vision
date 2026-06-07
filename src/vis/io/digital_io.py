from __future__ import annotations

import threading
from abc import ABC, abstractmethod


class DigitalIO(ABC):
    """A set of digital outputs (e.g. ejector solenoids)."""

    @abstractmethod
    def write(self, channel: int, value: bool) -> None: ...

    def pulse(self, channel: int, ms: int) -> None:
        """Drive a channel high for `ms`, then low (default: timer-based)."""
        self.write(channel, True)
        threading.Timer(ms / 1000.0, lambda: self.write(channel, False)).start()

    def close(self) -> None:  # noqa: B027 - optional override
        pass


class SimulatedIO(DigitalIO):
    """Records output activity in memory — for dev (macOS), tests, and the
    simulation source. `pulse` is recorded instantly (no real timer)."""

    def __init__(self) -> None:
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
    """Digital outputs over Modbus TCP (e.g. a remote I/O block on the line).

    Real driver for the line PC; requires `pip install '.[io]'`. Writes coils
    (one per output channel).
    """

    def __init__(self, host: str, port: int = 502, unit: int = 1) -> None:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:
            raise RuntimeError(
                "pymodbus not installed. Install it with: pip install '.[io]'"
            ) from exc
        self._client = ModbusTcpClient(host, port=port)
        self._unit = unit
        if not self._client.connect():
            raise RuntimeError(f"cannot connect to Modbus device at {host}:{port}")

    def write(self, channel: int, value: bool) -> None:
        self._client.write_coil(channel, bool(value), slave=self._unit)

    def close(self) -> None:
        self._client.close()
