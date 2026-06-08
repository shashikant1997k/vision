import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from vis.tools import build_tool, registered_types  # noqa: E402
from vis.tools.general import register_template  # noqa: E402


def _blob(size=(60, 80), present=True):
    img = np.full((*size, 3), 240, np.uint8)  # light background
    if present:
        cv2.rectangle(img, (15, 15), (45, 65), (30, 30, 30), -1)  # dark object
    return img


def test_tools_are_registered():
    for t in ("presence", "measure", "color_check", "template_match", "ocv_font"):
        assert t in registered_types()


def test_presence_present_and_absent():
    present = build_tool("presence", "p", {"mode": "present", "min_coverage": 0.05})
    assert present.inspect(_blob(present=True)).passed
    assert not present.inspect(_blob(present=False)).passed
    absent = build_tool("presence", "p", {"mode": "absent", "min_coverage": 0.05})
    assert absent.inspect(_blob(present=False)).passed


def test_measure_width_within_range():
    tool = build_tool("measure", "m", {"axis": "width", "min_px": 20, "max_px": 40})
    r = tool.inspect(_blob(present=True))  # object is ~31 px wide (15..45)
    assert r.passed and "px" in r.measured_value
    too_strict = build_tool("measure", "m", {"axis": "width", "min_px": 50, "max_px": 60})
    assert not too_strict.inspect(_blob(present=True)).passed


def test_color_check_tolerance():
    img = np.full((20, 20, 3), [200, 50, 50], np.uint8)  # reddish
    ok = build_tool("color_check", "c", {"target": [200, 50, 50], "tolerance": 30})
    assert ok.inspect(img).passed
    bad = build_tool("color_check", "c", {"target": [50, 50, 200], "tolerance": 30})
    assert not bad.inspect(img).passed


def test_template_match_golden():
    golden = _blob(present=True)
    tpl = register_template(golden)
    tool = build_tool("template_match", "t", {"template": tpl, "min_score": 0.7})
    assert tool.inspect(golden).passed                  # same artwork -> match
    assert not tool.inspect(_blob(present=False)).passed  # blank -> no match
