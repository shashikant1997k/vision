import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("qrcode")

import cv2  # noqa: E402
import qrcode  # noqa: E402

from vis.cli import _gs1  # noqa: E402
from vis.common.types import ROI  # noqa: E402
from vis.domain.entities import Fixture, Recipe, Region, ToolSpec  # noqa: E402
from vis.engine.frame import Frame  # noqa: E402
from vis.engine.pipeline import InspectionPipeline  # noqa: E402
from vis.engine.pool import SyncPool  # noqa: E402
from vis.runtime.locator import encode_template, locate  # noqa: E402


def _qr(data, size):
    q = qrcode.QRCode(border=1, box_size=4)
    q.add_data(data)
    q.make(fit=True)
    img = np.array(q.make_image(fill_color="black", back_color="white").convert("RGB"), np.uint8)
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_NEAREST)


_TPL_ROI = ROI(28, 44, 116, 44)  # bounding box of the "REF" marker


def _scene(offx, offy):
    """A frame with a distinctive marker (the locator template) + a QR, shifted
    by (offx, offy) to simulate the part moving on the line."""
    img = np.full((400, 520, 3), 255, np.uint8)
    cv2.putText(img, "REF", (32 + offx, 78 + offy), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    qr = _qr(_gs1("SN0001"), 120)
    img[150 + offy : 270 + offy, 200 + offx : 320 + offx] = qr
    return img


def _recipe(with_fixture):
    region = Region(
        "r", "P1", ROI(180, 140, 160, 140), "lane1",
        [ToolSpec("code1", "code_verify", ROI(20, 10, 120, 120), {"gs1": True, "expected_data": _gs1("SN0001")})],
    )
    if with_fixture:
        master = _scene(0, 0)
        region.fixture = Fixture(
            template=encode_template(master, _TPL_ROI), anchor_x=_TPL_ROI.x, anchor_y=_TPL_ROI.y
        )
    return Recipe("rec", "Demo", 1, [region])


def test_locate_finds_part_offset():
    master = _scene(0, 0)
    fixture = Fixture(template=encode_template(master, _TPL_ROI), anchor_x=_TPL_ROI.x, anchor_y=_TPL_ROI.y)
    dx, dy, score = locate(_scene(25, 18), fixture)
    assert score > 0.7
    assert abs(dx - 25) <= 2 and abs(dy - 18) <= 2


def test_fixture_makes_rois_follow_the_part():
    shifted = _scene(25, 18)
    # without a fixture the ROI stays put and misses the shifted QR -> reject
    r0 = InspectionPipeline(_recipe(False), SyncPool()).process_frame(Frame("f", 0, shifted, 0.0))
    assert not all(x.passed for x in r0)
    # with a fixture the ROIs follow the part -> pass
    r1 = InspectionPipeline(_recipe(True), SyncPool()).process_frame(Frame("f", 0, shifted, 0.0))
    assert all(x.passed for x in r1)
