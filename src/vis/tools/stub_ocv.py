from __future__ import annotations

from .base import InspectionTool, ToolResult
from .registry import register


@register
class StubOCVTool(InspectionTool):
    """Placeholder OCV tool for the walking skeleton.

    The real Phase-1 implementation is ONNX PaddleOCR (PP-OCR mobile),
    recognition-only on the ROI, compared to the expected string (docs/05).
    For now it 'reads' the value the FakeCamera encoded into pixel [0, 0] and
    verifies it matches the expected value from the recipe — enough to exercise
    the full crop -> worker -> aggregate -> reject path end to end.
    """

    type = "ocv_stub"

    def inspect(self, roi_image) -> ToolResult:
        expected = str(self.config.get("expected", ""))
        # First pixel, whether the frame is colour (H,W,3) or mono (H,W): a real
        # Mono8 GigE camera delivers 2-D arrays, the sim delivers 3-D.
        measured = str(int(roi_image.reshape(-1)[0])) if roi_image.size else ""
        passed = measured == expected
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=measured,
            expected_value=expected,
            confidence=1.0 if passed else 0.0,
            model_version="stub-0",
        )
