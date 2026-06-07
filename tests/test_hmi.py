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
