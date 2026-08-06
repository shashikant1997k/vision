"""Runs of identical characters must not be miscounted.

Recognition-only OCR reads a smooth run of identical glyphs as fewer than there
are — "MRP00000" came back as "MRP0000" at a healthy 0.75 confidence, so nothing
downstream could tell it was wrong. In pharma that turns 100.00 into 10.00.

The detector counts them correctly but costs ~50x more, so it is spent only when
the read contains a long run. These tests pin both halves: the fix works, and it
does not slow down text without runs.
"""

from __future__ import annotations


import pytest

from vis.tools.ocr import _has_long_run

pytest.importorskip("rapidocr_onnxruntime")


@pytest.fixture(scope="module")
def read():
    from vis.tools.readers import get_text_reader

    reader = get_text_reader()
    return lambda img: reader(img, {})[0]


@pytest.fixture(scope="module")
def render():
    from tests.test_ocr_bench import _render_text

    return _render_text


# ---- the trigger ---------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("0000", True), ("00000", True), ("MRP00000", True), ("AAAA", True),
    ("000", False),            # 3 reads correctly and appears in real prices
    ("M.R.P Rs. 000.00", False),
    ("B.No.TEST12345", False), ("EXP. 10/2026", False), ("", False),
])
def test_long_run_detection(text, expected):
    assert _has_long_run(text) is expected


def test_run_detection_ignores_spaces():
    assert _has_long_run("0 0 0 0")


# ---- the behaviour -------------------------------------------------------
@pytest.mark.parametrize("text", ["0000", "00000", "000000", "MRP00000", "AAAA"])
def test_repeated_characters_are_counted_correctly(read, render, text):
    assert read(render(text, 360, 90)) == text


def test_short_runs_still_read(read, render):
    assert read(render("000", 360, 90)) == "000"


def test_text_without_runs_is_unaffected(read, render):
    for text in ("LOT42", "EXP1026", "Per XX Tablets"):
        assert read(render(text, 600, 90)) == text


def test_detector_rescue_can_be_disabled_for_cycle_time(read, render, monkeypatch):
    """A line with a tight budget can forbid the 300 ms rescue."""
    monkeypatch.setenv("VIS_OCR_DETECTOR_FALLBACK", "0")
    assert read(render("00000", 360, 90)) != "00000"      # the old, wrong behaviour
    monkeypatch.setenv("VIS_OCR_DETECTOR_FALLBACK", "1")
    assert read(render("00000", 360, 90)) == "00000"


def test_no_run_means_no_detector_cost(read, render):
    """Text without a run must never pay for the detector."""
    import time

    image = render("B.No.TEST12345", 600, 90)
    read(image)                                   # warm the engine
    start = time.perf_counter()
    read(image)
    assert (time.perf_counter() - start) * 1000 < 150, "the detector should not have run"


def test_fallback_env_var_parsing(monkeypatch):
    from vis.tools.ocr import _detector_fallback_enabled

    for value, enabled in (("0", False), ("false", False), ("no", False),
                           ("1", True), ("yes", True), ("", True)):
        monkeypatch.setenv("VIS_OCR_DETECTOR_FALLBACK", value)
        assert _detector_fallback_enabled() is enabled
    monkeypatch.delenv("VIS_OCR_DETECTOR_FALLBACK")
    assert _detector_fallback_enabled() is True
