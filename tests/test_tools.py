import numpy as np

from vis.tools import build_tool, registered_types


def test_ocv_stub_registered():
    assert "ocv_stub" in registered_types()


def test_ocv_stub_pass_and_fail():
    tool = build_tool("ocv_stub", "t1", {"expected": 42})

    img = np.zeros((20, 50, 3), dtype=np.uint8)
    img[0, 0, 0] = 42
    assert tool.inspect(img).passed

    img[0, 0, 0] = 7
    result = tool.inspect(img)
    assert not result.passed
    assert result.measured_value == "7"
    assert result.expected_value == "42"


def test_build_unknown_tool_raises():
    try:
        build_tool("does_not_exist", "t1")
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown tool type")
