"""The inline last-reject panel — answer 'what did it look like?' on the live screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.engine.frame import Frame  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.hmi.main_window import MainWindow  # noqa: E402
from vis.tools.base import ToolResult  # noqa: E402


def Region(passed, tool_results=(), region_id="region1"):
    """A real RegionResult — the overlay renderer needs the genuine article."""
    from vis.engine.aggregator import RegionResult

    return RegionResult(
        frame_id=0, camera_id="cam1", region_id=region_id,
        reject_output="lane1", passed=passed, tool_results=list(tool_results),
    )


@pytest.fixture
def window(tmp_path):
    QApplication.instance() or QApplication([])
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


def _add_reject(window, frame_id, regions):
    image = (np.random.rand(60, 90, 3) * 255).astype("uint8")
    window._failed_log.add(Frame("cam1", frame_id, image, timestamp=float(frame_id)), regions)


def test_hidden_until_something_is_rejected(window):
    assert not window._last_reject_img.isVisible()
    assert not window._last_reject_head.isVisible()


def test_appears_with_an_image_after_a_reject(window):
    _add_reject(window, 7, [Region(False, [ToolResult("ocv-1", False, "ABC", "XYZ")])])
    window._update_last_reject()
    assert window._last_reject_img.isVisibleTo(window)
    pixmap = window._last_reject_img.pixmap()
    assert pixmap is not None and not pixmap.isNull(), "the operator must see the image"


def test_reason_names_the_tool_and_what_it_read(window):
    """'failed' is useless — say which inspection failed and why."""
    _add_reject(window, 7, [Region(False, [ToolResult("expiry", False, "10/2028", "10/2026")])])
    window._update_last_reject()
    text = window._last_reject_txt.text()
    assert "expiry" in text and "10/2028" in text and "10/2026" in text


def test_reason_falls_back_when_there_are_no_details(window):
    _add_reject(window, 8, [Region(False, [ToolResult("presence", False)])])
    window._update_last_reject()
    assert "presence" in window._last_reject_txt.text()


def test_reason_summarises_instead_of_flooding_the_panel(window):
    tools = [ToolResult(f"t{i}", False, "a", "b") for i in range(5)]
    _add_reject(window, 9, [Region(False, tools)])
    window._update_last_reject()
    assert "+3 more" in window._last_reject_txt.text()


def test_passing_tools_are_not_reported_as_reasons(window):
    _add_reject(window, 10, [Region(False, [
        ToolResult("good", True, "ok", "ok"), ToolResult("bad", False, "x", "y"),
    ])])
    window._update_last_reject()
    text = window._last_reject_txt.text()
    assert "bad" in text and "good" not in text


def test_updates_to_the_newest_reject(window):
    _add_reject(window, 1, [Region(False, [ToolResult("first", False)])])
    window._update_last_reject()
    _add_reject(window, 2, [Region(False, [ToolResult("second", False)])])
    window._update_last_reject()
    assert "second" in window._last_reject_txt.text()


def test_repeat_refreshes_do_not_redraw(window):
    """_update_last_reject runs on every refresh tick — it must be cheap."""
    _add_reject(window, 3, [Region(False, [ToolResult("t", False)])])
    window._update_last_reject()
    before = window._last_reject_id
    window._update_last_reject()
    assert window._last_reject_id == before
