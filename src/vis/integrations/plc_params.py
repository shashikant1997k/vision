"""PLC parameter table — read/write named PLC registers from the HMI.

The CodeScan "PLC Parameters" screen lets maintenance read a named PLC register
(conveyor speed, reject delay, a timer preset, …), edit it, and upload the new
value. This module provides that generic register read/write behind a small
`RegisterClient` seam so it works against a real Modbus PLC in production and an
in-memory simulator in dev/tests.

The parameter *definitions* (name → address/kind) are persisted in app settings;
the live *values* are read from the PLC on demand, never stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PlcParameter:
    name: str
    address: int
    kind: str = "holding"  # holding (register) | coil (bit)

    def to_dict(self) -> dict:
        return {"name": self.name, "address": self.address, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> PlcParameter:
        return cls(
            name=str(d.get("name", "")),
            address=int(d.get("address", 0)),
            kind=d.get("kind", "holding"),
        )


@runtime_checkable
class RegisterClient(Protocol):
    def read(self, address: int, kind: str = "holding") -> int: ...
    def write(self, address: int, value: int, kind: str = "holding") -> None: ...
    def close(self) -> None: ...


class SimulatedRegisterClient:
    """In-memory registers — for dev and tests (and when no PLC is configured)."""

    def __init__(self, initial: dict | None = None) -> None:
        self._regs: dict[tuple[str, int], int] = {}
        for (kind, addr), val in (initial or {}).items():
            self._regs[(kind, addr)] = int(val)

    def read(self, address: int, kind: str = "holding") -> int:
        return int(self._regs.get((kind, int(address)), 0))

    def write(self, address: int, value: int, kind: str = "holding") -> None:
        self._regs[(kind, int(address))] = int(value)

    def close(self) -> None:
        pass


class ModbusRegisterClient:
    """Read/write Modbus TCP holding registers and coils on a line PLC."""

    def __init__(self, host: str, port: int = 502, unit: int = 1) -> None:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pymodbus not installed. Install it with: pip install '.[io]'") from exc
        self._client = ModbusTcpClient(host, port=port)
        if not self._client.connect():
            raise RuntimeError(f"cannot connect to PLC at {host}:{port}")
        self._unit = unit

    def read(self, address: int, kind: str = "holding") -> int:  # pragma: no cover (needs PLC)
        if kind == "coil":
            rr = self._client.read_coils(int(address), 1, slave=self._unit)
            return int(bool(rr.bits[0]))
        rr = self._client.read_holding_registers(int(address), 1, slave=self._unit)
        return int(rr.registers[0])

    def write(self, address: int, value: int, kind: str = "holding") -> None:  # pragma: no cover
        if kind == "coil":
            self._client.write_coil(int(address), bool(value), slave=self._unit)
        else:
            self._client.write_register(int(address), int(value), slave=self._unit)

    def close(self) -> None:  # pragma: no cover
        self._client.close()


def read_all(client: RegisterClient, params: list[PlcParameter]) -> dict[str, int]:
    """Read every parameter's current value. Unreadable params are omitted."""
    out: dict[str, int] = {}
    for p in params:
        try:
            out[p.name] = client.read(p.address, p.kind)
        except Exception:
            continue
    return out


def upload(client: RegisterClient, params: list[PlcParameter], values: dict[str, int]) -> list[str]:
    """Write the given new values (by parameter name). Returns the names written."""
    by_name = {p.name: p for p in params}
    written: list[str] = []
    for name, value in values.items():
        p = by_name.get(name)
        if p is None or value is None:
            continue
        client.write(p.address, int(value), p.kind)
        written.append(name)
    return written
