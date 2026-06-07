from dataclasses import dataclass

import pytest

from vis.cli import build_code_demo_recipe
from vis.engine.pool import SyncPool
from vis.io import RejectController, RejectOutputConfig, SimulatedIO
from vis.io.digital_io import ModbusTcpIO
from vis.runtime import InspectionRunner

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402

_NOW = lambda d, fn: fn()  # immediate scheduler for deterministic tests  # noqa: E731


@dataclass
class _RR:
    reject_output: str


def test_simulated_io_records_pulses():
    io = SimulatedIO()
    io.pulse(2, 100)
    io.pulse(2, 100)
    assert io.pulse_count(2) == 2
    assert (2, True) in io.events and (2, False) in io.events


def test_reject_controller_pulses_correct_lane():
    io = SimulatedIO()
    rc = RejectController(
        [RejectOutputConfig("lane1", channel=1), RejectOutputConfig("lane2", channel=2)],
        io=io,
        scheduler=_NOW,
    )
    rc.reject(_RR("lane2"))
    assert io.pulse_count(2) == 1
    assert io.pulse_count(1) == 0
    assert rc.fired == 1


def test_reject_controller_unknown_lane_is_counted_not_fired():
    io = SimulatedIO()
    rc = RejectController([RejectOutputConfig("lane1", channel=1)], io=io, scheduler=_NOW)
    rc.reject(_RR("lane9"))
    assert rc.fired == 0 and rc.unmatched == 1


def test_runtime_drives_ejector():
    recipe = build_code_demo_recipe()
    lanes = sorted({r.reject_output for r in recipe.regions})
    io = SimulatedIO()
    rc = RejectController(
        [RejectOutputConfig(lane, channel=i + 1) for i, lane in enumerate(lanes)],
        io=io,
        scheduler=_NOW,
    )
    camera = SimulatedCodeCamera("cam1", recipe, num_frames=3, defect_rate=1.0, seed=0)
    InspectionRunner([(camera, recipe)], SyncPool(), reject_handler=rc).run()

    expected = 3 * len(recipe.regions)
    assert rc.fired == expected
    assert sum(io.pulse_count(i + 1) for i in range(len(lanes))) == expected


def test_modbus_io_clear_error_without_driver():
    with pytest.raises(RuntimeError):
        ModbusTcpIO("127.0.0.1", port=1)  # pymodbus not installed in dev
