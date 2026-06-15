"""Trusted-time controls: clock-jump detection, anomaly recording, NTP gating."""

from vis.common.trusted_time import (
    TimeMonitor,
    detect_clock_jump,
    now_iso,
    record_time_anomaly,
)
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.users import UserService


def test_now_iso_is_utc_offset_aware():
    ts = now_iso()
    assert ts.endswith("+00:00")  # never a naive local timestamp


def test_no_jump_within_tolerance():
    # wall advanced ~the same as monotonic -> no anomaly
    assert detect_clock_jump(100.0, 1000.0, 105.0, 1005.3, tolerance=2.0) is None


def test_backward_jump_is_critical():
    # monotonic advanced 5 s but wall went BACK an hour -> backdating
    a = detect_clock_jump(100.0, 5000.0, 105.0, 5000.0 - 3600 + 5, tolerance=2.0)
    assert a is not None and a["direction"] == "backward"
    assert a["severity"] == "critical" and a["kind"] == "CLOCK_JUMP"
    assert a["magnitude_s"] < 0


def test_forward_jump_detected():
    a = detect_clock_jump(100.0, 5000.0, 105.0, 5000.0 + 600, tolerance=2.0)
    assert a is not None and a["direction"] == "forward" and a["magnitude_s"] > 0


def test_monitor_with_injected_clocks_fires_callback():
    seen = []
    # fake clocks: __init__ reads once (0.0/1000.0); check reads mono=5, wall=905
    # -> monotonic advanced 5s but wall went back 95s
    monos = iter([0.0, 5.0])
    walls = iter([1000.0, 905.0])
    mon = TimeMonitor(seen.append, mono_fn=lambda: next(monos),
                      wall_fn=lambda: next(walls), tolerance=2.0)
    anomaly = mon.check_skew()
    assert anomaly is not None and anomaly["direction"] == "backward"
    assert seen and seen[0]["kind"] == "CLOCK_JUMP"


def test_record_time_anomaly_writes_audit_and_event(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    UserService(sf).seed_roles()

    anomaly = {"kind": "CLOCK_JUMP", "severity": "critical",
               "direction": "backward", "magnitude_s": -3600.0}
    record_time_anomaly(sf, anomaly)

    from vis.db.app_settings import EventService
    from vis.db.audit_review import AuditReviewService

    events = EventService(sf).list_events()
    assert any(e["source"] == "time" and "CLOCK_JUMP" in e["message"] for e in events)
    # the audit entry is classified CRITICAL by the review taxonomy
    pending = AuditReviewService(sf).pending(None)
    assert any(f["code"] == "CLOCK_CHANGE" and f["severity"] == "critical"
               for f in pending["flags"])


def test_ntp_check_noop_without_server():
    mon = TimeMonitor(lambda a: None, ntp_server=None)
    assert mon.check_ntp() is None
