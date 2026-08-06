"""Reports hub — batch records, rejects, events and audit on one screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.hmi.main_window import MainWindow  # noqa: E402
from vis.hmi.reports_hub import ReportsHubWindow  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    win = MainWindow(
        username="op1",
        recipe=build_code_demo_recipe(),
        camera_factory=lambda c, s, r: SimulatedCodeCamera(c, r, num_frames=None),
        session_factory=make_session_factory(engine),
        simulation=True,
    )
    yield win
    win.close()


def test_hub_builds_tabs_lazily(app):
    """Opening Reports must not query every report up front."""
    built = []

    def factory(name):
        def make():
            built.append(name)
            return QLabel(name)
        return make

    hub = ReportsHubWindow([("A", factory("A")), ("B", factory("B"))])
    assert built == ["A"], "only the visible tab should be built"
    hub._tabs.setCurrentIndex(1)
    assert built == ["A", "B"]


def test_a_broken_report_does_not_break_the_screen(app):
    def explode():
        raise RuntimeError("database is on fire")

    hub = ReportsHubWindow([("Bad", explode), ("Good", lambda: QLabel("ok"))])
    assert hub._tabs.count() == 2                      # screen survives
    hub._tabs.setCurrentIndex(1)
    assert hub._tabs.count() == 2


def test_factories_returning_none_are_skipped(app):
    hub = ReportsHubWindow([("Skipped", None), ("Kept", lambda: QWidget())])
    assert [hub._tabs.tabText(i) for i in range(hub._tabs.count())] == ["Kept"]


def test_open_reports_offers_the_expected_tabs(window):
    window.open_reports()
    hubs = window.findChildren(ReportsHubWindow)
    assert hubs, "Reports did not open"
    tabs = [hubs[0]._tabs.tabText(i) for i in range(hubs[0]._tabs.count())]
    assert "Batch orders" in tabs and "Events" in tabs


def test_every_tab_can_be_opened(window):
    window.open_reports()
    hub = window.findChildren(ReportsHubWindow)[0]
    for i in range(hub._tabs.count()):
        hub._tabs.setCurrentIndex(i)          # must not raise
    assert hub._tabs.count() >= 2


def test_scattered_report_buttons_are_gone(window):
    """One Reports entry replaces the separate Batches/Review/Events buttons."""
    assert hasattr(window, "_reports_btn")
    assert not hasattr(window, "_review")
    assert not hasattr(window, "_batches_btn")


def test_reject_count_surfaces_on_the_button(window):
    """An operator should see there is something to review without opening it."""
    import numpy as np

    from vis.engine.frame import Frame

    assert window._reports_btn.text() == "Reports…"
    frame = Frame("cam1", 1, np.zeros((8, 8, 3), np.uint8), timestamp=1.0)
    window._failed_log.add(frame, [])
    window._refresh()                      # the real update path
    assert "1 rejects" in window._reports_btn.text()
