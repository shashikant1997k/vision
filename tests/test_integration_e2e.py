"""End-to-end third-party integration: settings/events services, the comms
screen config, and a live run streaming results to a real TCP client while
driving the 24V signal outputs."""

import json
import os
import socket

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("qrcode")

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.app_settings import EventService, SettingsService  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    admin = users.create_user("admin", "Secret123", roles=("admin",))
    return sf, admin


def test_settings_service_roundtrip(tmp_path):
    sf, _ = _setup(tmp_path)
    service = SettingsService(sf)
    assert service.get("comms") is None
    service.set("comms", {"tcp_enabled": True, "tcp_port": 9999})
    assert service.get("comms")["tcp_port"] == 9999
    service.set("comms", {"tcp_enabled": False})
    assert service.get("comms") == {"tcp_enabled": False}


def test_event_service_log_and_filter(tmp_path):
    sf, _ = _setup(tmp_path)
    events = EventService(sf)
    events.log("info", "run", "Inspection started")
    events.log("alarm", "line", "5 consecutive rejects")
    assert len(events.list_events()) == 2
    alarms = events.list_events(severity="alarm")
    assert len(alarms) == 1 and alarms[0]["message"].startswith("5 consecutive")


def test_comms_window_saves_and_applies(tmp_path):
    _qapp()
    sf, admin = _setup(tmp_path)
    from vis.hmi.comms_window import CommsWindow, load_comms_config

    applied = []
    win = CommsWindow(sf, apply_callback=applied.append)
    win._tcp_enabled.setChecked(True)
    win._tcp_port.setValue(9555)
    win._channels["ready"].setValue(1)
    win._channels["reject_pulse"].setValue(4)
    win._save()
    assert applied and applied[0]["tcp_port"] == 9555
    saved = load_comms_config(sf)
    assert saved["tcp_enabled"] is True
    assert saved["signals"]["ready"] == 1 and saved["signals"]["reject_pulse"] == 4


def test_live_run_streams_results_and_drives_signals(tmp_path):
    """The full loop: comms enabled -> window starts the protocol server and
    line signals; a TCP client receives state + per-product results + alarm;
    the 24V outputs pulse PASS/REJECT and latch ALARM."""
    _qapp()
    sf, admin = _setup(tmp_path)
    SettingsService(sf).set("comms", {
        "tcp_enabled": True, "tcp_port": 0, "allow_remote_start": False,
        "io_backend": "simulated",
        "signals": {"ready": 1, "running": 2, "pass_pulse": 3, "reject_pulse": 4,
                    "alarm": 5, "heartbeat": 0},
    })

    from vis.hmi.main_window import MainWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=8, defect_rate=1.0, seed=2)

    win = MainWindow(username="admin", recipe=build_code_demo_recipe(),
                     camera_factory=factory, session_factory=sf, user_id=admin,
                     alarm_consecutive_rejects=3)
    assert win._proto is not None and win._signals is not None
    io = win._signals.io
    assert (1, True) in io.events  # READY high at startup

    client = socket.create_connection(("127.0.0.1", win._proto.port), timeout=2)
    reader = client.makefile("r")
    assert json.loads(reader.readline())["type"] == "hello"

    win.start()
    if win._runner is not None:
        win._runner.join()
    win._refresh()  # triggers the consecutive-reject ALARM

    # the client received state -> results -> alarm
    types = []
    for _ in range(40):
        message = json.loads(reader.readline())
        types.append(message["type"])
        if message["type"] == "alarm":
            assert message["code"] == "CONSECUTIVE_REJECTS"
            break
    assert "state" in types and "result" in types and "alarm" in types

    # 24V side: RUNNING toggled, REJECT pulsed, ALARM latched
    assert (2, True) in io.events and (2, False) in io.events
    assert io.pulse_count(4) > 0
    assert (5, True) in io.events
    assert win._signals.alarm

    # operational events were logged
    events = EventService(sf).list_events()
    sources = {e["source"] for e in events}
    assert "run" in sources and "line" in sources

    client.close()
    win.close()  # fail-safe: READY drops, server stops
    assert (1, False) in io.events


def test_remote_start_signal_is_thread_safe(tmp_path):
    _qapp()
    sf, admin = _setup(tmp_path)
    SettingsService(sf).set("comms", {"tcp_enabled": True, "tcp_port": 0,
                                      "allow_remote_start": True, "signals": {}})

    from vis.hmi.main_window import MainWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=1, defect_rate=0.0, seed=0)

    win = MainWindow(username="admin", recipe=build_code_demo_recipe(),
                     camera_factory=factory, session_factory=sf, user_id=admin)
    client = socket.create_connection(("127.0.0.1", win._proto.port), timeout=2)
    reader = client.makefile("r")
    reader.readline()  # hello
    client.sendall(b'{"cmd":"start","id":1}\n')
    reply = json.loads(reader.readline())
    assert reply["ok"] is True

    app = _qapp()
    for _ in range(50):
        app.processEvents()  # deliver the queued cross-thread signal
        if win._runner is not None:
            break
    assert win._runner is not None  # remote start reached the GUI thread
    win._runner.join()
    win.stop()
    client.close()
    win.close()
