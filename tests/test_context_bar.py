"""The persistent context bar — what is running, and who is running it.

The content area is a stack, so without this bar the batch/product/user context
disappears the moment an operator opens Settings or Products. Auditors expect to
read it from any screen (the pattern the plants' existing system establishes).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.hmi.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(tmp_path):
    QApplication.instance() or QApplication([])
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    win = MainWindow(
        username="operator1",
        recipe=build_code_demo_recipe(),
        camera_factory=lambda cid, s, r: SimulatedCodeCamera(cid, r, num_frames=None),
        session_factory=make_session_factory(engine),
        simulation=True,
    )
    yield win
    win.close()


def test_context_bar_exists_and_shows_the_user(window):
    assert window._context_bar is not None
    assert window._ctx_user.text() == "operator1"


def test_shows_test_mode_when_no_batch_is_selected(window):
    assert window._ctx_batch.text() == "TEST / SETUP"


def test_shows_the_selected_product(window):
    assert window._ctx_product.text() not in ("", "—")


def test_context_survives_navigating_away_from_the_live_page(window):
    """The whole point: open Settings and the context is still readable."""
    before = window._ctx_batch.text()
    window.open_settings()
    assert window._context_bar.parent() is not None
    assert window._ctx_batch.text() == before


def test_running_batch_reads_as_live(window):
    window._batch_id = 42
    window._refresh_context_bar()
    assert "1b8a4b" in window._ctx_batch.styleSheet(), "a running batch must stand out"
    window._batch_id = None
    window._refresh_context_bar()
    assert "1b8a4b" not in window._ctx_batch.styleSheet()


def test_refresh_is_safe_before_the_bar_exists(window):
    """It is called from _on_batch_selected during construction, before the
    bar is built — it must no-op rather than raise."""
    delattr(window, "_ctx_batch")
    window._refresh_context_bar()
