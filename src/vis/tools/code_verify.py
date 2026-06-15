from __future__ import annotations

from .base import InspectionTool, ToolResult
from .decode import decode_first
from .grading import approximate_grade
from .gs1 import canonical_date, named, parse_gs1, validate_gs1
from .registry import register


@register
class CodeVerifyTool(InspectionTool):
    """Reads a 1D/2D code, optionally parses its GS1 AIs, verifies content
    against expected values, and attaches an approximate process-control grade.

    Config:
      gs1:             bool — parse GS1 AIs (default True)
      validate:        bool — enforce GS1 structural rules (GTIN/SSCC check
                              digits, real YYMMDD dates, CSET-82); default True
                              when gs1 is on
      expected_data:   str  — exact decoded string to match (optional)
      expected_fields: dict — {field_name: value} to match, e.g.
                              {"gtin": "...", "batch": "...", "expiry": "..."}
                              (date fields compare canonically: DD=00 == last day)
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
        gs1_on = self.config.get("gs1", True)
        if gs1_on:
            parsed = parse_gs1(decoded.text)
            fields = named(parsed)
            detail["fields"] = fields
        else:
            parsed = {}
            fields = {}

        passed = True
        mismatches: dict = {}

        # Structural validation (check digits, real dates, charset) — a wrong
        # check digit or impossible date is a defective code, not just a mismatch.
        if gs1_on and self.config.get("validate", True):
            errors = validate_gs1(parsed)
            if errors:
                passed = False
                detail["invalid"] = errors

        for key, expected in (self.config.get("expected_fields") or {}).items():
            actual = fields.get(key)
            # dates compare canonically (the DD=00 "last day" convention)
            if key in ("expiry", "production_date", "best_before") and actual is not None:
                match = canonical_date(actual) == canonical_date(str(expected))
            else:
                match = actual == expected
            if not match:
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
