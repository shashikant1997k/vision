import pytest

pytest.importorskip("rapidocr_onnxruntime")

from vis.cli import build_ocr_demo_recipe  # noqa: E402
from vis.engine.pipeline import InspectionPipeline  # noqa: E402
from vis.engine.pool import SyncPool  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera, _render_text  # noqa: E402
from vis.tools import build_tool  # noqa: E402


def _img(text, w=360, h=90):
    return _render_text(text, w, h)


def test_ocr_reads_and_matches_expected():
    tool = build_tool("ocv_text", "lot", {"expected": "LOT42", "uppercase": True})
    result = tool.inspect(_img("LOT42"))
    assert result.passed
    assert result.measured_value == "LOT42"
    assert result.confidence > 0.5


def test_ocr_mismatch_fails():
    tool = build_tool("ocv_text", "lot", {"expected": "LOT42", "uppercase": True})
    result = tool.inspect(_img("LOT49"))
    assert not result.passed
    assert result.measured_value == "LOT49"


def test_ocr_reads_rotated_text():
    import numpy as np

    upright = _render_text("LOT42", 360, 90)
    rotated = np.rot90(upright, 1)  # text now sideways in the image
    # rotation=270 un-rotates the ROI before reading
    tool = build_tool("ocv_text", "lot", {"expected": "LOT42", "uppercase": True, "rotation": 270})
    assert tool.inspect(rotated).passed


def test_ocr_sideways_multiword_auto_orients_and_orders():
    import numpy as np

    # a multi-word line, rotated sideways, no rotation set -> must auto-orient and
    # read in left-to-right order (not scrambled)
    upright = _render_text("MFG 102025", 420, 90)
    sideways = np.rot90(upright, 1)
    tool = build_tool("ocv_text", "mfg", {"expected": "MFG 102025", "uppercase": True})
    result = tool.inspect(sideways)
    # the digits should appear in order somewhere in the read
    assert "102025" in result.measured_value.replace(" ", "")


def test_ocr_matching_tolerates_spaces_and_punctuation():
    from vis.tools.ocr import _match_key

    # a '.'/',' slip, a missing dot, or extra spaces must not fail the match —
    # matching compares alphanumeric content only (independent of OCR accuracy)
    assert _match_key("MFG, 10/2025") == _match_key("MFG. 10/2025")
    assert _match_key("EXP 10/2026") == _match_key("EXP. 10/2026")
    assert _match_key("B.NO.  TEST12345") == _match_key("B.NO. TEST12345")
    assert _match_key("M.R.P RS. 000.00") == _match_key("MRP Rs 000 00")


def test_ocr_regex_validates_date_format():
    tool = build_tool("ocv_text", "exp", {"match": "regex", "pattern": r"\d{4}/\d{2}"})
    assert tool.inspect(_img("2026/06")).passed


def test_ocr_pipeline_reads_text_and_code():
    recipe = build_ocr_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool())
    results = [
        r
        for f in SimulatedCodeCamera("cam1", recipe, num_frames=1, defect_rate=0.0).frames()
        for r in pipeline.process_frame(f)
    ]
    assert results and all(r.passed for r in results)
    lot_results = [tr for r in results for tr in r.tool_results if tr.tool_id.endswith("_lot")]
    assert lot_results and all(tr.measured_value == "LOT42" for tr in lot_results)


def test_confusables_do_not_reject_real_print():
    """The exact failure from the user's real blister: OCR read 'B.N0.TEST12345'
    (zero) for printed 'B.No.TEST12345' — a 0/O lookalike must not reject."""
    from vis.tools.ocr import _match_key
    from vis.tools.readers import register_text_reader

    assert _match_key("B.N0.TEST12345") == _match_key("B.No.TEST12345")
    assert _match_key("EXP.1O/2O26") == _match_key("EXP.10/2026")   # O read for 0
    assert _match_key("LOT5") == _match_key("L0TS")                  # S/5, O/0
    assert _match_key("MFG.10/2025") != _match_key("MFG.10/2026")    # real diffs still fail

    # deterministic end-to-end via the reader seam (no OCR engine involved)
    register_text_reader("fake_blister", lambda img, cfg: ("B.N0.TEST12345", 0.93))
    tool = build_tool(
        "ocv_text", "bno",
        {"reader": "fake_blister", "match": "exact", "expected": "B.No.TEST12345"},
    )
    import numpy as np

    assert tool.inspect(np.zeros((20, 80, 3), dtype=np.uint8)).passed


def test_single_line_recognition_first_still_reads():
    # the rec-first strategy must read clean single-line crops (short-circuit path)
    tool = build_tool("ocv_text", "lot", {"expected": "LOT42", "uppercase": True})
    result = tool.inspect(_img("LOT42"))
    assert result.passed and "LOT42" in result.measured_value.replace(" ", "")
