import numpy as np

from vis.tools import build_tool
from vis.tools.readers import (
    available_text_readers,
    get_text_reader,
    register_text_reader,
)


def test_pluggable_text_reader_via_config():
    # a "paid library" registers itself; selected by tool config — no built-in OCR
    register_text_reader("fake_sdk", lambda img, cfg: ("LOT42", 0.99))
    tool = build_tool("ocv_text", "t", {"reader": "fake_sdk", "match": "exact", "expected": "LOT42"})
    result = tool.inspect(np.zeros((20, 60, 3), dtype=np.uint8))
    assert result.passed and result.measured_value == "LOT42"


def test_reader_registry_defaults_and_lists():
    assert "builtin" in available_text_readers()
    assert get_text_reader("does-not-exist") is get_text_reader("builtin")


def test_reader_selected_by_env(monkeypatch):
    register_text_reader("envreader", lambda img, cfg: ("XX", 0.5))
    monkeypatch.setenv("VIS_TEXT_READER", "envreader")
    assert get_text_reader() is get_text_reader("envreader")
