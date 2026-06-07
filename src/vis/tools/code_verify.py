from __future__ import annotations

from .base import InspectionTool, ToolResult
from .decode import decode_first
from .grading import approximate_grade
from .gs1 import named, parse_gs1
from .registry import register


@register
class CodeVerifyTool(InspectionTool):
    """Reads a 1D/2D code, optionally parses its GS1 AIs, verifies content
    against expected values, and attaches an approximate process-control grade.

    Config:
      gs1:             bool — parse GS1 AIs (default True)
      expected_data:   str  — exact decoded string to match (optional)
      expected_fields: dict — {field_name: value} to match, e.g.
                              {"gtin": "...", "batch": "...", "expiry": "..."}
    """

    type = "code_verify"

    def inspect(self, roi_image) -> ToolResult:
        from .transform import rotate_image

        roi_image = rotate_image(roi_image, self.config.get("rotation", 0))
        decoded = decode_first(roi_image)
        grade = approximate_grade(roi_image, decoded.ok)
        detail: dict = {"symbology": decoded.symbology, "grade": grade}

        expected_data = self.config.get("expected_data")

        if not decoded.ok:
            detail["reason"] = "no_decode"
            return ToolResult(
                tool_id=self.tool_id,
                passed=False,
                measured_value=None,
                expected_value=expected_data,
                confidence=0.0,
                detail=detail,
            )

        detail["raw"] = decoded.text
        if self.config.get("gs1", True):
            fields = named(parse_gs1(decoded.text))
            detail["fields"] = fields
        else:
            fields = {}

        passed = True
        mismatches: dict = {}

        for key, expected in (self.config.get("expected_fields") or {}).items():
            actual = fields.get(key)
            if actual != expected:
                passed = False
                mismatches[key] = {"expected": expected, "actual": actual}

        if expected_data is not None and decoded.text != expected_data:
            passed = False
            mismatches["_raw"] = {"expected": expected_data, "actual": decoded.text}

        # Variable code: validate the decoded data against a regex pattern
        # (e.g. a serial/date format) instead of a fixed value.
        pattern = self.config.get("pattern")
        if pattern:
            import re

            if not re.fullmatch(pattern, decoded.text):
                passed = False
                mismatches["_pattern"] = {"pattern": pattern, "actual": decoded.text}

        if mismatches:
            detail["mismatches"] = mismatches

        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=decoded.text,
            expected_value=expected_data,
            confidence=1.0 if passed else 0.0,
            detail=detail,
        )
