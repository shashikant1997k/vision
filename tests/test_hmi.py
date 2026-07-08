import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # headless Qt for CI/tests

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vis.hmi.image import numpy_to_qpixmap  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_numpy_to_qpixmap(qapp):
    img = np.zeros((20, 30, 3), dtype=np.uint8)
    img[:, :, 1] = 255
    pix = numpy_to_qpixmap(img)
    assert pix.width() == 30 and pix.height() == 20


def test_login_dialog_authenticates(qapp, tmp_path):
    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.users import UserService
    from vis.hmi.login import LoginDialog

    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    users = UserService(make_session_factory(engine))
    users.seed_roles()
    users.create_user("op", "Secret123", roles=("operator",))

    dialog = LoginDialog(users)
    dialog._username.setText("op")
    dialog._password.setText("Secret123")
    dialog._try_login()
    assert dialog.user_id is not None and dialog.username == "op"

    bad = LoginDialog(users)
    bad._username.setText("op")
    bad._password.setText("wrong")
    bad._try_login()
    assert bad.user_id is None and bad._error.text()


def test_main_window_runs_and_counts(qapp):
    pytest.importorskip("qrcode")
    from vis.cli import build_code_demo_recipe
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.main_window import MainWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=2, defect_rate=0.0, seed=0)

    window = MainWindow(username="op", recipe=build_code_demo_recipe(), camera_factory=factory)
    window.start()
    if window._runner is not None:
        window._runner.join()  # wait for the bounded sim source to finish
    window._refresh()
    assert int(window._total.text()) > 0
    window.stop()
    assert window._runner is None


def test_main_window_multi_camera(qapp):
    pytest.importorskip("qrcode")
    from vis.cli import build_code_demo_recipe
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.main_window import MainWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=3, defect_rate=0.0, seed=0)

    window = MainWindow(
        username="op", recipe=build_code_demo_recipe(), camera_factory=factory,
        camera_ids=["cam1", "cam2", "cam3"],
    )
    assert window._cam_tabs.count() == 3                # one tab per camera
    assert set(window._cam_images) == {"cam1", "cam2", "cam3"}
    window.start()
    if window._runner is not None:
        window._runner.join()
    window._refresh()
    snap = window._stats.snapshot()
    assert {"cam1", "cam2", "cam3"} <= set(snap)        # all cameras produced results
    window.stop()


def test_main_window_per_camera_recipes(qapp, tmp_path):
    pytest.importorskip("qrcode")
    from vis.cli import build_code_demo_recipe, build_ocr_demo_recipe
    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.store import RecipeRepository
    from vis.db.users import UserService
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.main_window import MainWindow

    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    repo = RecipeRepository(sf)
    r1 = repo.save_draft(build_code_demo_recipe(), user_id=qa)
    repo.approve(r1, qa, "Secret123", "r")
    r2 = repo.save_draft(build_ocr_demo_recipe(), user_id=qa)
    repo.approve(r2, qa, "Secret123", "r")

    def factory(cid, settings, recipe):
        return SimulatedCodeCamera(cid, recipe, num_frames=2, defect_rate=0.0, seed=0)

    win = MainWindow(
        username="op", recipe=build_code_demo_recipe(), camera_factory=factory,
        camera_ids=["cam1", "cam2"], session_factory=sf, user_id=qa,
    )
    # a station config can pre-select each camera's recipe at construction
    win2 = MainWindow(
        username="op", recipe=build_code_demo_recipe(), camera_factory=factory,
        camera_ids=["cam1", "cam2"], camera_recipe_ids={"cam1": r1, "cam2": r2},
        session_factory=sf, user_id=qa,
    )
    assert win2._recipe_combo.currentData() == r1
    assert win2._cam_recipe_combos["cam2"].currentData() == r2

    win._recipe_combo.setCurrentIndex(win._recipe_combo.findData(r1))           # cam1 = code recipe
    win._cam_recipe_combos["cam2"].setCurrentIndex(win._cam_recipe_combos["cam2"].findData(r2))  # cam2 = ocr
    win.start()
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    types1 = {t.tool_type for r in win._cam_recipes["cam1"].regions for t in r.tools}
    types2 = {t.tool_type for r in win._cam_recipes["cam2"].regions for t in r.tools}
    assert types1 != types2  # the two cameras run different recipes
    win.stop()


def test_main_window_yield_reasons_and_reject_review(qapp):
    pytest.importorskip("qrcode")
    from vis.cli import build_code_demo_recipe
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.main_window import MainWindow
    from vis.hmi.review_window import ReviewWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=8, defect_rate=1.0, seed=2)

    window = MainWindow(username="op", recipe=build_code_demo_recipe(), camera_factory=factory)
    window.start()
    if window._runner is not None:
        window._runner.join()
    window._refresh()
    assert "%" in window._yield.text()                 # yield shown
    assert "reject reasons" in window._reasons.text().lower()  # reason breakdown
    assert len(window._failed_log) > 0                 # rejects captured for review

    review = ReviewWindow(window._failed_log, window._recipe)
    assert review._counter.text().startswith("Reject ") and "/" in review._counter.text()
    # the big red 'why' panel names the failed field(s) with the read value
    assert "✗" in review._why.text() and "read" in review._why.text()
    window.stop()
    assert window._state.text() == "● Idle"
