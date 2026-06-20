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
    for w in (win._teach, win._teach_files, win._emulate, win._import, win._stations,
              win._settings, win._admin):
        assert w.isHidden()
    # run controls remain
    assert not win._start.isHidden() and not win._review.isHidden()


def test_admin_sees_everything(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    admin = users.create_user("boss", "Secret123", roles=("admin",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="boss", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(), session_factory=sf, user_id=admin)
    for w in (win._teach, win._settings, win._admin, win._stations):
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
    assert win._sidebar_widget.isHidden()  # auto-collapsed after navigation
    prev = win._current_panel_window
    win.open_comms()  # switching panels replaces the previous one
    assert win._content_stack.currentWidget() is not live
    assert win._current_panel_window is not prev
    win._navigate_home()
    assert win._content_stack.currentWidget() is live
    assert not win._sidebar_widget.isHidden()
    assert win._current_panel_window is None


def test_consecutive_reject_alarm_stops_the_line(tmp_path):
    _qapp()
    sf, users = _setup(tmp_path)
    op = users.create_user("op", "Secret123", roles=("operator",))
    from vis.hmi.main_window import MainWindow

    win = MainWindow(username="op", recipe=build_code_demo_recipe(),
                     camera_factory=_factory(defect_rate=1.0, frames=8),
                     session_factory=sf, user_id=op, alarm_consecutive_rejects=3)
    win.start()
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    assert "ALARM" in win._state.text()
    assert win._runner is None  # line stopped


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
