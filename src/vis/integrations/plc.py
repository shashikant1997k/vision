"""PLC / fieldbus link — publish inspection results and counters to a line PLC.

Lines commonly require the vision system to hand results to a PLC over a fieldbus
(EtherNet/IP, PROFINET, Modbus TCP) with a handshake, rather than only a digital
pulse. This module defines a small `PlcLink` interface and provides:

- RecordingPlcLink — in-memory, for dev/tests.
- ModbusPlcLink   — real, writes a pass/fail coil + counters to holding registers
                    (pip install '.[io]'); PROFINET is typically reached through a
                    Modbus/PROFINET gateway, so this covers many lines.
- EtherNetIpPlcLink — real, writes named tags on an Allen-Bradley/CIP PLC
                    (pip install pycomm3).

A production handler subscribes it to the EventBus ("inspection.result").
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlcLink(Protocol):
    def write_result(self, region_result) -> None: ...
    def write_counters(self, totals: dict) -> None: ...
    def close(self) -> None: ...


class RecordingPlcLink:
    """Records what would be written — for dev and tests."""

    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []
        self.counters: list[dict] = []

    def write_result(self, region_result) -> None:
        self.results.append(
            (region_result.region_id, bool(region_result.passed), region_result.reject_output or "")
        )

    def write_counters(self, totals: dict) -> None:
        self.counters.append(dict(totals))

    def on_result(self, region_result) -> None:  # EventBus hook
        self.write_result(region_result)

    def close(self) -> None:
        pass


class ModbusPlcLink:
    """Write results/counters to a PLC over Modbus TCP holding registers + coils.

    Register map (configurable base): coil `result_coil` = pass(1)/fail(0);
    holding regs from `counter_base` = [total, passed, failed].
    """

    def __init__(self, host, port=502, unit=1, result_coil=0, counter_base=0):
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pymodbus not installed. Install it with: pip install '.[io]'") from exc
        self._client = ModbusTcpClient(host, port=port)
        if not self._client.connect():
            raise RuntimeError(f"cannot connect to PLC at {host}:{port}")
        self._unit = unit
        self._result_coil = result_coil
        self._counter_base = counter_base

    def write_result(self, region_result) -> None:
        self._client.write_coil(self._result_coil, bool(region_result.passed), slave=self._unit)

    def write_counters(self, totals: dict) -> None:
        regs = [int(totals.get("total", 0)), int(totals.get("passed", 0)), int(totals.get("failed", 0))]
        self._client.write_registers(self._counter_base, regs, slave=self._unit)

    def on_result(self, region_result) -> None:
        self.write_result(region_result)

    def close(self) -> None:
        self._client.close()


class EtherNetIpPlcLink:
    """Write named tags on an Allen-Bradley / CIP PLC (EtherNet/IP) via pycomm3.

    tags: {"result": "Vision.Pass", "total": "Vision.Total", ...}
    """

    def __init__(self, host, tags: dict):
        try:
            from pycomm3 import LogixDriver
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pycomm3 not installed. Install it with: pip install pycomm3") from exc
        self._plc = LogixDriver(host)
        self._plc.open()
        self._tags = tags

    def write_result(self, region_result) -> None:
        if "result" in self._tags:
            self._plc.write((self._tags["result"], bool(region_result.passed)))

    def write_counters(self, totals: dict) -> None:
        writes = [(self._tags[k], int(totals.get(k, 0))) for k in ("total", "passed", "failed") if k in self._tags]
        if writes:
            self._plc.write(*writes)

    def on_result(self, region_result) -> None:
        self.write_result(region_result)

    def close(self) -> None:
        self._plc.close()
