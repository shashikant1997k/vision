"""Print-quality inspection as a recipe tool ("Print Inspect").

The grading maths already lived in :mod:`print_quality` (ISO-15415-style A–F
bands from contrast, stroke consistency, dropout, sharpness and character
placement) but was only reachable from the teach screen. This wraps it as a
registered tool so a recipe can *reject on print quality* — the case where the
text is correct but the coder is fading, smearing or dropping strokes.

Why it is a separate tool from OCV: reading the right characters and printing
them well are different questions. A drifting inkjet still reads correctly long
before it becomes illegible; grading catches it while it is still a maintenance
job rather than a batch deviation.

config:
    min_grade   "A".."D" — worst acceptable grade (default "C")
    style       "solid" | "dotted" — print technology (dot-matrix scores
                fragmentation differently); default "solid"
    reference   {"median_stroke_px": float} taught from a known-good sample.
                Without it, uniform fade/smear that shifts the WHOLE line can
                evade the line's own-median comparison — so teach it when you
                care about slow drift.
    min_chars   minimum characters expected; fewer means the print is largely
                missing, which fails regardless of the grade (default 1)
"""

from __future__ import annotations

from .base import InspectionTool, ToolResult
from .print_quality import GRADES, grade_line
from .registry import register


@register
class PrintInspectTool(InspectionTool):
    """Grade the print in the ROI and pass/fail against a minimum grade."""

    type = "print_inspect"

    def inspect(self, roi_image) -> ToolResult:
        min_grade = str(self.config.get("min_grade", "C")).upper()[:1] or "C"
        if min_grade not in GRADES:
            min_grade = "C"
        style = str(self.config.get("style", "solid"))
        reference = self.config.get("reference") or None
        min_chars = int(self.config.get("min_chars", 1))

        try:
            report = grade_line(roi_image, reference=reference, style=style)
        except Exception as exc:  # a grading failure must not crash the line
            return ToolResult(
                tool_id=self.tool_id,
                passed=False,
                measured_value="grading failed",
                expected_value=f"≥ {min_grade}",
                model_version="print_inspect",
                detail={"error": str(exc)},
            )

        grade = report.get("grade", "F")
        n_chars = int(report.get("n_chars", 0))
        # index 0 is the best grade, so "worse" means a HIGHER index
        too_poor = GRADES.index(grade) > GRADES.index(min_grade)
        too_few = n_chars < min_chars
        passed = not (too_poor or too_few)

        if too_few:
            measured = f"grade {grade}, only {n_chars} character(s)"
        else:
            measured = f"grade {grade} ({n_chars} chars)"
        worst = _worst_characters(report)
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=measured,
            expected_value=f"≥ {min_grade}",
            confidence=_grade_confidence(grade),
            model_version="print_inspect",
            detail={
                "grade": grade,
                "n_chars": n_chars,
                "median_stroke_px": report.get("median_stroke_px"),
                "worst_characters": worst,
                "style": style,
                "referenced": bool(reference),
            },
        )


def _grade_confidence(grade: str) -> float:
    """A–F mapped to 1.0–0.0 so the HMI can show a bar like every other tool."""
    if grade not in GRADES:
        return 0.0
    span = max(len(GRADES) - 1, 1)
    return round(1.0 - GRADES.index(grade) / span, 3)


def _worst_characters(report: dict, limit: int = 3) -> list[dict]:
    """The characters dragging the grade down — this is what a maintenance
    engineer actually needs ("nozzle 4 is fading"), not just a letter."""
    chars = [c for c in report.get("chars", []) if not c.get("empty")]
    ranked = sorted(chars, key=lambda c: GRADES.index(c.get("grade", "F")), reverse=True)
    return [
        {
            "index": report.get("chars", []).index(c),
            "grade": c.get("grade"),
            "stroke_width_px": round(float(c.get("stroke_width_px", 0.0)), 2),
        }
        for c in ranked[:limit]
    ]


def teach_reference(image, style: str = "solid") -> dict:
    """Signature of a known-good sample, to store in the tool's ``reference``.
    Call this at teach time on the golden crop."""
    report = grade_line(image, style=style)
    return {"median_stroke_px": report.get("median_stroke_px", 0.0)}
