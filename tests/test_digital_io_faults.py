"""Digital-output fault handling — the line must never be silently unprotected."""

from __future__ import annotations

import threading
import time

import pytest

from vis.io.digital_io import DigitalIO, IOFault, ModbusTcpIO, SimulatedIO


class FakeResult:
    def __init__(self, error: bool = False) -> None:
        self._error = error

    def isError(self) -> bool:  # noqa: N802 - pymodbus API name
        return self._error


class FakeClient:
    """Stands in for pymodbus's ModbusTcpClient."""

    def __init__(self, *, connect_ok=True, fail_writes=0, raise_writes=0) -> None:
        self.connect_ok = connect_ok
        self.fail_writes = fail_writes      # respond with isError() this many times
        self.raise_writes = raise_writes    # raise this many times
        self.writes: list[tuple[int, bool]] = []
        self.connects = 0
        self.closes = 0

    def connect(self) -> bool:
        self.connects += 1
        return self.connect_ok

    def close(self) -> None:
        self.closes += 1

    def write_coil(self, channel, value, slave=1):
        if self.raise_writes > 0:
            self.raise_writes -= 1
            raise OSError("connection reset by peer")
        if self.fail_writes > 0:
            self.fail_writes -= 1
            return FakeResult(error=True)
        self.writes.append((channel, bool(value)))
        return FakeResult()


def test_connect_failure_is_explicit():
    with pytest.raises(IOFault, match="cannot connect"):
        ModbusTcpIO("10.0.0.9", client=FakeClient(connect_ok=False))


def test_successful_write_is_recorded_and_healthy():
    c = FakeClient()
    io = ModbusTcpIO("10.0.0.9", client=c)
    io.write(3, True)
    assert c.writes == [(3, True)]
    assert io.healthy and io.write_count == 1 and io.fault_count == 0


def test_error_response_is_not_silently_ignored():
    """pymodbus signals failure in the RESPONSE — an unchecked write does nothing."""
    io = ModbusTcpIO("10.0.0.9", client=FakeClient(fail_writes=99), retry=False)
    with pytest.raises(IOFault):
        io.write(1, True)
    assert not io.healthy and io.fault_count == 1


def test_dropped_connection_recovers_on_retry():
    c = FakeClient(raise_writes=1)          # first write dies, reconnect succeeds
    io = ModbusTcpIO("10.0.0.9", client=c)
    io.write(2, True)                        # must not raise
    assert c.writes == [(2, True)]
    assert io.healthy and c.connects == 2    # initial + reconnect


def test_persistent_failure_raises_and_marks_unhealthy():
    io = ModbusTcpIO("10.0.0.9", client=FakeClient(raise_writes=99))
    with pytest.raises(IOFault, match="NOT being protected"):
        io.write(2, True)
    assert not io.healthy


def test_fault_callback_fires_once_per_transition():
    events = []
    c = FakeClient(raise_writes=99)
    io = ModbusTcpIO("10.0.0.9", client=c, on_fault=lambda ok, d: events.append(ok))
    for _ in range(3):
        with pytest.raises(IOFault):
            io.write(1, True)
    assert events == [False]                 # one alarm, not three

    c.raise_writes = 0                       # link comes back
    io.write(1, True)
    assert events == [False, True]


def test_callback_exception_cannot_break_io():
    def boom(ok, detail):
        raise ValueError("HMI blew up")

    io = ModbusTcpIO("10.0.0.9", client=FakeClient(raise_writes=99), on_fault=boom)
    with pytest.raises(IOFault):             # the IO fault, not ValueError
        io.write(1, True)


# ---- pulse scheduler ------------------------------------------------------
class RecordingIO(DigitalIO):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()
        self.events: list[tuple[int, bool]] = []

    def write(self, channel: int, value: bool) -> None:
        with self.lock:
            self.events.append((channel, bool(value)))


def test_pulse_turns_the_channel_off():
    io = RecordingIO()
    io.pulse(5, 20)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with io.lock:
            if (5, False) in io.events:
                break
        time.sleep(0.01)
    with io.lock:
        assert io.events[0] == (5, True)
        assert (5, False) in io.events, "channel was left energised"
    io.close()


def test_many_pulses_share_one_thread():
    """A fast line must not spawn a thread per reject."""
    io = RecordingIO()
    before = threading.active_count()
    for ch in range(40):
        io.pulse(ch, 10)
    assert threading.active_count() - before <= 2
    io.close()


def test_failing_turn_off_does_not_kill_the_scheduler():
    class FlakyIO(RecordingIO):
        def write(self, channel: int, value: bool) -> None:
            if channel == 1 and value is False:
                raise IOFault("nope")
            super().write(channel, value)

    io = FlakyIO()
    io.pulse(1, 5)      # this turn-off raises
    io.pulse(2, 5)      # this one must still happen
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with io.lock:
            if (2, False) in io.events:
                break
        time.sleep(0.01)
    with io.lock:
        assert (2, False) in io.events
    io.close()


def test_close_drops_pending_channels():
    io = RecordingIO()
    io.pulse(7, 10_000)          # would stay on for 10 s
    io.close()
    with io.lock:
        assert (7, False) in io.events


def test_simulated_io_still_records_pulses():
    io = SimulatedIO()
    io.pulse(1, 50)
    assert io.pulse_count(1) == 1
    assert io.events == [(1, True), (1, False)]
