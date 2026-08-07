"""Production operator-flow behaviours: role-gated HMI, consecutive-reject
line-stop alarm, simulation banner, forced password change, duplicate batches."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("qrcode")

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.batches import BatchService  # noqa: E402
from vis.db.store import RecipeRepository  # noqa: E402
from vis.db.users import AuthError, UserService  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.runtime import LiveStats  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    return sf, users


def _factory(defect_rate=0.0, frames=3):
    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=frames, defect_rate=defect_rate, seed=1)

    return factory


def test_operator_sees_run_only_screen(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    op = users.create_user("op", "Secret123", roles=("operator",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(), session_factory=sf, user_id=op)
    # engineering/admin controls are hidden, not just permission-blocked
    for w in (win._teach, win._teach_files, win._import, win._settings, win._admin):
        assert w.isHidden()
    # run controls remain (rejects/records now live behind the Reports screen)
    assert not win._start.isHidden() and not win._reports_btn.isHidden()


def test_admin_sees_everything(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(), session_factory=sf, user_id=admin)
    for w in (win._teach, win._settings, win._admin):
        assert not w.isHidden()


def test_in_place_panel_navigation(tmp_path):
    """Sidebar screens render in the content stack (not pop-up windows), tear
    down the previous panel when switching, and home returns to the live view."""
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(), session_factory=sf, user_id=admin)
    live = win._live_page
    win.open_admin()
    assert win._content_stack.currentWidget() is not live
    assert not win._sidebar_widget.isHidden()  # navigation must NOT collapse the menu
    prev = win._current_panel_window
    win.open_comms()  # switching panels replaces the previous one
    assert win._content_stack.currentWidget() is not live
    assert win._current_panel_window is not prev
    win._navigate_home()
    assert win._content_stack.currentWidget() is live
    assert win._current_panel_window is None
    # the menu collapses ONLY via the toggle
    win._toggle_sidebar()
    assert win._sidebar_widget.isHidden()
    win._toggle_sidebar()
    assert not win._sidebar_widget.isHidden()


def test_product_batch_run_records_to_batch(tmp_path):
    """Full flow: approve a job, create a batch order, select it on the line, run
    — results are recorded against that batch."""
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.db.batches import BatchService
    from vis.db.store import RecipeRepository

    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=admin)  # auto-creates product
    repo.approve(rid, admin, "Secret123", "Released")
    bid = BatchService(sf).start(rid, "B-001", admin)

    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=0.0, frames=4),
                     session_factory=sf, user_id=admin)
    win._reload_open_batches()
    idx = win._batch_combo.findData(bid)
    assert idx > 0  # the open batch appears in the run selector
    win._batch_combo.setCurrentIndex(idx)
    win.start()
    assert win._batch_id == bid  # run is bound to the selected batch
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    recorded = next(b for b in BatchService(sf).list_batches() if b["id"] == bid)
    assert recorded["total"] > 0  # results saved against the batch


def test_consecutive_reject_alarm_stops_the_line(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    op = users.create_user("op", "Secret123", roles=("operator",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=1.0, frames=8),
                     session_factory=sf, user_id=op, alarm_consecutive_rejects=3)
    win.start()
    win._batch_id = 1  # the line-stop alarm only guards a running production batch
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    assert "ALARM" in win._state.text()
    assert win._runner is None  # line stopped


def test_a_new_batch_starts_from_zero(tmp_path):
    """The second batch must not open showing the first batch's totals, lanes
    or yield — that is a batch record reporting product it never inspected."""
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.db.batches import BatchService
    from vis.db.store import RecipeRepository
    from vis.hmi.main_window import MainWindow

    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=admin)
    repo.approve(rid, admin, "Secret123", "Released")
    batches = BatchService(sf)
    first = batches.start(rid, "B-001", admin)

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=0.0, frames=6),
                     session_factory=sf, user_id=admin)
    # Restarting after a Stop normally opens the modal OEE "why was the line
    # down?" prompt, which nothing can answer in a headless run.
    win._classify_downtime = lambda: None

    def run(batch_id):
        win._reload_open_batches()
        win._batch_combo.setCurrentIndex(win._batch_combo.findData(batch_id))
        win.start()
        if win._runner is not None:
            win._runner.join()
        win.stop()

    run(first)
    after_first = win._stats.totals()
    assert after_first["total"] > 0
    assert win._stats_batch_id == first

    # close it and open a second batch on the same line
    batches.close(first, admin, "Secret123", "Batch complete")
    second = batches.start(rid, "B-002", admin)
    run(second)

    after_second = win._stats.totals()
    assert win._stats_batch_id == second
    assert after_second["total"] == after_first["total"], "counters carried over"
    for cam in win._stats.snapshot().values():
        assert cam["total"] == after_second["total"]        # per camera zeroed
        for lane in cam.get("lanes", {}).values():
            assert lane["total"] <= after_second["total"]   # per lane zeroed
    win.close()


def test_batch_start_is_logged_once_then_resumed(tmp_path):
    """A batch starts ONCE. Logging every Stop/Start as "started" made the audit
    trail read as eleven separate batches."""
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.db.app_settings import EventService
    from vis.db.batches import BatchService
    from vis.db.store import RecipeRepository
    from vis.hmi.main_window import MainWindow

    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=admin)
    repo.approve(rid, admin, "Secret123", "Released")
    bid = BatchService(sf).start(rid, "B-777", admin)

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=0.0, frames=2),
                     session_factory=sf, user_id=admin)
    win._classify_downtime = lambda: None
    win._reload_open_batches()
    win._batch_combo.setCurrentIndex(win._batch_combo.findData(bid))

    for _ in range(3):                      # start, stop, start, stop, start, stop
        win.start()
        if win._runner is not None:
            win._runner.join()
        win.stop()
    win.close()

    messages = [e["message"] for e in EventService(sf).list_events()
                if e["source"] == "batch"]
    assert sum("B-777 started" in m for m in messages) == 1
    assert sum("B-777 resumed" in m for m in messages) == 2


def _teach_trigger_probe(tmp_path, monkeypatch, mode, source=""):
    """Open live Teach on a fake camera and report whether free-run was forced."""
    from vis.camera.settings import CameraSettings, TriggerConfig
    from vis.camera.settings_store import save_settings
    from vis.hmi.main_window import MainWindow

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    save_settings("cam1", CameraSettings(trigger=TriggerConfig(mode=mode, source=source)))

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=0.0, frames=50))
    forced = []
    monkeypatch.setattr(win, "_force_free_run", lambda src: forced.append(True))
    win._open_live_teach()
    return win, bool(forced)


def test_teach_uses_the_configured_trigger_not_free_run(tmp_path, monkeypatch):
    """Teaching on forced free-run taught the recipe on bench frames — different
    exposure moment, no strobe — and it then behaved differently in production.
    A triggered camera must teach on the same trigger the line will run on."""
    _qapp()
    from vis.camera.settings import TriggerMode

    win, forced = _teach_trigger_probe(tmp_path, monkeypatch,
                                       TriggerMode.HARDWARE, "Line0")
    assert not forced, "Teach overrode the hardware trigger"
    win.close()


def test_teach_still_free_runs_a_continuous_camera(tmp_path, monkeypatch):
    """Bench teaching on a free-running camera must be unchanged."""
    _qapp()
    from vis.camera.settings import TriggerMode

    win, forced = _teach_trigger_probe(tmp_path, monkeypatch, TriggerMode.CONTINUOUS)
    assert forced
    win.close()


def test_simulation_banner_state():
    _qapp()
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(), simulation=True)
    assert win._simulation is True  # banner branch constructed without error


def test_live_stats_consecutive_counter():
    from vis.engine.aggregator import RegionResult

    stats = LiveStats()

    def rr(passed):
        return RegionResult(0, "cam1", "r", "lane1", passed, [])

    for passed in (False, False, True, False, False, False):
        stats.record(rr(passed))
    assert stats.consecutive_failures() == 3  # streak resets on the pass


def test_live_stats_reset_clears_every_counter():
    from vis.engine.aggregator import RegionResult

    stats = LiveStats()
    stats.record(RegionResult(0, "cam1", "r", "lane1", False, []))
    stats.record(RegionResult(0, "cam2", "r", "lane2", True, []))
    stats.record_cycle(42.0)
    assert stats.totals()["total"] == 2

    stats.reset()

    assert stats.totals() == {"total": 0, "passed": 0, "failed": 0, "yield": 0.0}
    assert stats.snapshot() == {}            # per-camera AND per-lane gone
    assert stats.consecutive_failures() == 0
    assert stats.reject_reasons() == {}
    assert stats.cycle_ms() == {"last": 0.0, "avg": 0.0}


def test_change_own_password_and_forced_change_path(tmp_path):
    sf, users = _setup(tmp_path)
    uid = users.create_user("admin", "admin123", roles=("admin",))
    with pytest.raises(AuthError):
        users.change_own_password(uid, "wrong-old", "NewPass123")
    users.change_own_password(uid, "admin123", "NewPass123")
    assert users.authenticate("admin", "NewPass123") == uid
    with pytest.raises(AuthError):
        users.authenticate("admin", "admin123")  # default no longer works


def test_duplicate_open_batch_rejected(tmp_path):
    sf, users = _setup(tmp_path)
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=qa)
    repo.approve(rid, qa, "Secret123", "released")
    svc = BatchService(sf)
    bid = svc.start(rid, "B-DUP", qa)
    with pytest.raises(ValueError):
        svc.start(rid, "B-DUP", qa)  # same number, still open
    svc.close(bid, qa, "Secret123", "released")
    assert svc.start(rid, "B-DUP", qa) > bid  # allowed again once closed


def test_live_results_table_per_camera_lane(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    op = users.create_user("op", "Secret123", roles=("operator",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=0.5, frames=6),
                     camera_ids=["cam1", "cam2"], session_factory=sf, user_id=op,
                     alarm_consecutive_rejects=0)  # alarm off for this test
    win.start()
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    table = win._results_table
    assert table.rowCount() >= 2  # at least one lane row per camera
    cams = {table.item(r, 0).text() for r in range(table.rowCount())}
    assert cams == {"cam1", "cam2"}
    for r in range(table.rowCount()):
        total = int(table.item(r, 2).text())
        assert total == int(table.item(r, 3).text()) + int(table.item(r, 4).text())
        assert table.item(r, 5).text() in ("✓", "✗")  # live tick/cross present
    win.stop()
