"""VIS Integration Protocol v1: real-socket round-trips + 24V line signals."""

import json
import socket
import time

from vis.engine.aggregator import RegionResult
from vis.integrations.vis_protocol import VisProtocolServer, result_message
from vis.io import SimulatedIO
from vis.io.signals import LineSignals, SignalMap
from vis.tools.base import ToolResult


def _connect(server):
    client = socket.create_connection(("127.0.0.1", server.port), timeout=2)
    reader = client.makefile("r")
    hello = json.loads(reader.readline())
    assert hello["type"] == "hello" and hello["proto"] == "VIS/1"
    return client, reader


def _ask(client, reader, payload):
    client.sendall((json.dumps(payload) + "\n").encode())
    return json.loads(reader.readline())


def _region(passed=True):
    return RegionResult(
        frame_id=7, camera_id="cam1", region_id="region1", reject_output="lane2",
        passed=passed,
        tool_results=[ToolResult("code1", True, "0109\x1d21SN1", "0109...", 0.97,
                                 detail={"grade": {"overall": "A"}})],
    )


def test_commands_and_replies():
    server = VisProtocolServer(port=0, callbacks={
        "get_status": lambda: {"running": True, "batch": "B-1", "recipe": "Tablets v3"},
        "get_counters": lambda: {"total": 10, "passed": 9, "failed": 1, "yield": 90.0},
        "list_recipes": lambda: [{"id": 7, "name": "Tablets", "version": 3}],
    }).start()
    try:
        client, reader = _connect(server)
        assert _ask(client, reader, {"cmd": "hello", "id": 1})["proto"] == "VIS/1"
        assert _ask(client, reader, {"cmd": "ping", "id": 2})["pong"] is True

        status = _ask(client, reader, {"cmd": "get_status", "id": 3})
        assert status["ok"] and status["running"] and status["batch"] == "B-1"

        counters = _ask(client, reader, {"cmd": "get_counters", "id": 4})
        assert counters["total"] == 10 and counters["yield"] == 90.0

        recipes = _ask(client, reader, {"cmd": "list_recipes", "id": 5})
        assert recipes["recipes"][0]["name"] == "Tablets"

        unknown = _ask(client, reader, {"cmd": "explode", "id": 6})
        assert unknown["ok"] is False and unknown["error"] == "UNKNOWN_CMD"

        notallowed = _ask(client, reader, {"cmd": "start", "id": 7})
        assert notallowed["error"] == "NOT_ALLOWED"  # no start callback registered

        client.sendall(b"this is not json\n")
        bad = json.loads(reader.readline())
        assert bad["error"] == "BAD_JSON"
        client.close()
    finally:
        server.stop()


def test_result_push_with_sequence_and_gs_encoding():
    server = VisProtocolServer(port=0).start()
    try:
        client, reader = _connect(server)
        server.push_state(True, "B-9")
        state = json.loads(reader.readline())
        assert state["type"] == "state" and state["batch"] == "B-9"

        server.on_result(_region(passed=False))
        result = json.loads(reader.readline())
        assert result["type"] == "result" and result["passed"] is False
        assert result["batch"] == "B-9" and result["lane"] == "lane2"
        assert result["fields"][0]["grade"] == "A"
        assert "<GS>" in result["fields"][0]["value"]  # control chars sanitized
        assert result["seq"] > state["seq"]  # monotonic sequence

        server.push_alarm("CONSECUTIVE_REJECTS", "5 consecutive rejects")
        alarm = json.loads(reader.readline())
        assert alarm["type"] == "alarm" and alarm["code"] == "CONSECUTIVE_REJECTS"
        client.close()
    finally:
        server.stop()


def test_remote_start_callback_and_multi_client():
    started = []
    server = VisProtocolServer(port=0, callbacks={"start": lambda: started.append(1)}).start()
    try:
        c1, r1 = _connect(server)
        c2, r2 = _connect(server)
        assert server.client_count() == 2
        ok = _ask(c1, r1, {"cmd": "start", "id": 1})
        assert ok["ok"] is True and started == [1]

        server.push_alarm("X", "both clients receive pushes")
        assert json.loads(r1.readline())["type"] == "alarm"
        assert json.loads(r2.readline())["type"] == "alarm"
        c1.close()
        c2.close()
        time.sleep(0.1)
    finally:
        server.stop()


def test_result_message_schema():
    message = result_message(_region(), "B-1")
    assert message["camera"] == "cam1" and message["product"] == "region1"
    assert message["fields"][0]["id"] == "code1"
    assert message["fields"][0]["confidence"] == 0.97


def test_line_signals_levels_pulses_alarm_heartbeat():
    io = SimulatedIO()
    signals = LineSignals(io, SignalMap(ready=1, running=2, pass_pulse=3,
                                        reject_pulse=4, alarm=5, heartbeat=6,
                                        heartbeat_ms=10))
    signals.set_ready(True)
    signals.set_running(True)
    assert (1, True) in io.events and (2, True) in io.events

    signals.on_result(_region(passed=True))
    signals.on_result(_region(passed=False))
    assert io.pulse_count(3) == 1 and io.pulse_count(4) == 1

    signals.set_alarm(True)
    assert signals.alarm and (5, True) in io.events
    signals.reset_alarm()
    assert not signals.alarm and (5, False) in io.events

    signals.start_heartbeat()
    time.sleep(0.05)
    signals.stop_heartbeat()
    beats = [e for e in io.events if e[0] == 6]
    assert len(beats) >= 2  # toggling

    signals.close()
    assert io.events[-2:] == [(2, False), (1, False)]  # fail-safe drop


def test_unwired_channels_are_ignored():
    io = SimulatedIO()
    signals = LineSignals(io, SignalMap())  # nothing wired
    signals.set_ready(True)
    signals.on_result(_region(False))
    signals.start_heartbeat()
    signals.close()
    assert io.events == []  # no writes to channel 0
