from vis.engine.aggregator import _region_passed
from vis.tools.base import ToolResult


def _tr(tool_id, passed):
    return ToolResult(tool_id=tool_id, passed=passed)


def test_all_must_pass():
    required = {"qr": True, "text": True}
    assert _region_passed([_tr("qr", True), _tr("text", False)], "all", required) is False
    assert _region_passed([_tr("qr", True), _tr("text", True)], "all", required) is True


def test_any_passes():
    required = {"qr": True, "text": True}
    assert _region_passed([_tr("qr", True), _tr("text", False)], "any", required) is True
    assert _region_passed([_tr("qr", False), _tr("text", False)], "any", required) is False


def test_optional_inspection_does_not_reject():
    # only the QR is required; the text is informational -> text fail still PASSES
    required = {"qr": True, "text": False}
    assert _region_passed([_tr("qr", True), _tr("text", False)], "all", required) is True
    # but if the QR (required) fails -> reject
    assert _region_passed([_tr("qr", False), _tr("text", True)], "all", required) is False
