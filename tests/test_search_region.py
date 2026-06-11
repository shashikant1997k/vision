"""Two-region (search + read) model: an outer search window tolerates print
drift; the tool locates the text line inside it and reads tightly."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("rapidocr_onnxruntime")

from vis.common.types import ROI  # noqa: E402
from vis.domain.entities import Recipe, Region, ToolSpec  # noqa: E402
from vis.engine.frame import Frame  # noqa: E402
from vis.engine.pipeline import InspectionPipeline  # noqa: E402
from vis.engine.pool import SyncPool  # noqa: E402
from vis.engine.sim import _render_text  # noqa: E402
from vis.tools.transform import locate_text_band  # noqa: E402


def _scene(shift_x=0, shift_y=0):
    """LOT42 printed at a nominal spot, optionally drifted (like real print)."""
    canvas = np.full((220, 420, 3), 235, np.uint8)
    text = _render_text("LOT42", 200, 60)
    y0, x0 = 80 + shift_y, 100 + shift_x
    canvas[y0 : y0 + 60, x0 : x0 + 200] = text
    return canvas


def _recipe(margin):
    config = {"expected": "LOT42", "uppercase": True}
    if margin:
        config["search_margin"] = margin
    tool = ToolSpec("lot", "ocv_text", ROI(100, 80, 200, 60), config)  # nominal box
    return Recipe("r", "P", 1, [Region("r1", "P1", ROI(0, 0, 420, 220), "lane1", [tool])])


def _run(recipe, image):
    return InspectionPipeline(recipe, SyncPool()).process_frame(Frame("c", 0, image, 0.0))


def test_locate_text_band_picks_line_nearest_centre():
    canvas = np.full((180, 300), 250, np.uint8)
    canvas[20:40, 30:260] = 10    # top line
    canvas[80:100, 40:200] = 10   # middle line (nearest centre)
    canvas[150:170, 30:260] = 10  # bottom line
    band = locate_text_band(np.stack([canvas] * 3, axis=-1), pad=2)
    assert band.shape[0] <= 28           # a single line vertically, full width
    assert band.shape[1] == 300
    assert (band < 50).any()             # contains the dark text


def test_search_region_reads_drifted_print():
    drifted = _scene(shift_x=22, shift_y=18)  # print moved right+down
    # without a search region the nominal box clips the text -> partial/failed
    no_margin = _run(_recipe(0), drifted)[0]
    # with the outer search window the line is located and read -> PASS
    with_margin = _run(_recipe(40), drifted)[0]
    assert with_margin.passed, with_margin.tool_results[0].measured_value
    assert with_margin.tool_results[0].measured_value.replace(" ", "") == "LOT42"
    # the margin is what made the difference (drifted print defeats the bare box)
    assert not no_margin.passed or with_margin.passed


def test_search_region_centred_print_still_reads():
    centred = _scene()
    result = _run(_recipe(40), centred)[0]
    assert result.passed


def test_teach_defaults_and_splitter(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QSplitter

    QApplication.instance() or QApplication([])
    from vis.cli import build_code_demo_recipe
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.teach_window import TeachWindow

    frame = next(SimulatedCodeCamera("r", build_code_demo_recipe(), num_frames=1, defect_rate=0.0).frames())
    win = TeachWindow(user_id=1, reference_image=frame.image, session_factory=None, reject_lanes=["lane1"])
    assert isinstance(win.centralWidget(), QSplitter)  # resizable left/right

    win._arm_tool("ocv_text")
    win._on_roi_drawn(20, 20, 120, 40)
    tool = win._model.regions[0].tools[0]
    assert tool.config.get("search_margin") == 20  # outer search region by default

    win._selected = ("tool", 0, 0)
    win._load_properties()
    assert win._t_search.value() == 20
    win._t_search.setValue(45)  # operator widens the drift tolerance
    assert win._model.regions[0].tools[0].config.get("search_margin") == 45
