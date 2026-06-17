"""Read-only monitoring REST API: auth, GET-only, endpoint shapes, dashboard."""

import json
import urllib.error
import urllib.request

import pytest

from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.oee import OEEService
from vis.db.store import RecipeRepository, ResultStore
from vis.db.users import UserService
from vis.engine.aggregator import RegionResult
from vis.integrations.web_api import ReadOnlyApiServer
from vis.tools.base import ToolResult


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    batch_id = BatchService(sf).start(rid, "B-001", qa)
    store = ResultStore(sf, batch_id=batch_id)
    for i in range(10):
        store.on_result(RegionResult(i, "cam1", "r", "l", i % 5 != 0,
                                     [ToolResult("c", i % 5 != 0, "x", None, 1.0)]))
    OEEService(sf).set_target_rate(batch_id, 60)
    return sf, batch_id


def _get(server, path, token=None):
    req = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.status, resp.read()


def test_auth_required(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(sf, port=0, token="s3cret").start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(server, "/api/status")
        assert exc.value.code == 401
        status, body = _get(server, "/api/status", token="s3cret")
        assert status == 200 and "server_utc" in json.loads(body)
    finally:
        server.stop()


def test_get_only(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(sf, port=0, token="t").start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/status", method="POST",
            headers={"Authorization": "Bearer t"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=3)
        assert exc.value.code == 405  # writes rejected
    finally:
        server.stop()


def test_endpoints(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(
        sf, port=0, token="t",
        status_provider=lambda: {"running": True, "batch": "B-001"},
        counters_provider=lambda: {"total": 10, "passed": 8, "failed": 2, "yield": 80.0},
    ).start()
    try:
        _, body = _get(server, "/api/counters", token="t")
        assert json.loads(body)["total"] == 10

        _, body = _get(server, "/api/batches", token="t")
        assert json.loads(body)["batches"][0]["batch_no"] == "B-001"

        _, body = _get(server, f"/api/batch/{batch_id}", token="t")
        summary = json.loads(body)
        assert summary["batch_no"] == "B-001" and "reconciliation" in summary

        _, body = _get(server, f"/api/oee/{batch_id}", token="t")
        assert "oee" in json.loads(body)

        _, body = _get(server, f"/api/reconciliation/{batch_id}", token="t")
        assert "yield_pct" in json.loads(body)

        _, body = _get(server, "/api/events", token="t")
        assert "events" in json.loads(body)

        _, body = _get(server, "/api/audit", token="t")
        assert "entries" in json.loads(body)
    finally:
        server.stop()


def test_unknown_route_404(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(sf, port=0, token="t").start()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(server, "/api/nope", token="t")
        assert exc.value.code == 404
    finally:
        server.stop()


def test_dashboard_served_without_token(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(sf, port=0, token="t").start()
    try:
        status, body = _get(server, "/")  # the HTML page itself needs no token
        assert status == 200 and b"Live Monitor" in body
    finally:
        server.stop()


def test_access_is_counted(tmp_path):
    sf, batch_id = _setup(tmp_path)
    server = ReadOnlyApiServer(sf, port=0, token="t").start()
    try:
        _get(server, "/api/events", token="t")
        _get(server, "/api/events", token="t")
        assert server.access_count >= 2
    finally:
        server.stop()


def test_live_window_starts_web_server(tmp_path):
    import json as _json
    import os
    import urllib.request
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.db.app_settings import SettingsService
    from vis.hmi.main_window import MainWindow

    sf, batch_id = _setup(tmp_path)
    admin = UserService(sf).create_user("admin", "Secret123", roles=("admin",))
    SettingsService(sf).set("comms", {
        "web_enabled": True, "web_port": 0, "web_token": "tok123", "signals": {}})

    win = MainWindow(username="admin", recipe=build_code_demo_recipe(),
                     camera_factory=lambda *a: None, session_factory=sf, user_id=admin)
    try:
        assert win._web is not None
        req = urllib.request.Request(
            f"http://127.0.0.1:{win._web.port}/api/counters",
            headers={"Authorization": "Bearer tok123"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            assert resp.status == 200 and "total" in _json.loads(resp.read())
    finally:
        win.close()
