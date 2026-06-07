import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from vis.common.types import ROI  # noqa: E402
from vis.domain.entities import Recipe, Region, ToolSpec  # noqa: E402
from vis.runtime.resolve import required_batch_fields, resolve_batch_fields  # noqa: E402
from vis.tools.transform import rotate_image  # noqa: E402


def _recipe_with_batch_field():
    tool = ToolSpec(
        "lot", "ocv_text", ROI(0, 0, 50, 20),
        {"match": "batch_field", "field": "lot", "uppercase": True},
    )
    region = Region("region1", "Product 1", ROI(0, 0, 100, 100), "lane1", [tool])
    return Recipe("r", "Demo", 1, [region])


def test_required_batch_fields():
    assert required_batch_fields(_recipe_with_batch_field()) == ["lot"]


def test_resolve_batch_fields_fills_value():
    resolved = resolve_batch_fields(_recipe_with_batch_field(), {"lot": "TEST12345"})
    config = resolved.regions[0].tools[0].config
    assert config == {"match": "contains", "expected": "TEST12345", "uppercase": True}


def test_resolve_batch_fields_missing_value_stays_batch_field():
    resolved = resolve_batch_fields(_recipe_with_batch_field(), {})
    assert resolved.regions[0].tools[0].config["match"] == "batch_field"


def test_rotate_image_90():
    img = np.zeros((4, 6, 3), dtype=np.uint8)
    assert rotate_image(img, 90).shape == (6, 4, 3)
    assert rotate_image(img, 0).shape == (4, 6, 3)


def test_batch_data_dialog_collects():
    import pytest

    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.batch_data_dialog import BatchDataDialog

    dlg = BatchDataDialog("B-01", ["lot", "expiry"])
    dlg._inputs["lot"].setText("TEST12345")
    dlg._inputs["expiry"].setText("10/2026")
    assert dlg.batch_no() == "B-01"
    assert dlg.values() == {"lot": "TEST12345", "expiry": "10/2026"}
