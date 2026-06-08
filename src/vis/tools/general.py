"""General-purpose inspection tools (beyond OCR/code): presence/absence,
measurement, colour, and golden-template compare. Each is a registered
InspectionTool that takes an ROI image and returns a ToolResult, so they compose
in a recipe exactly like the code/text tools and feed the same pass/fail logic,
reject I/O, stats, and reports.
"""

from __future__ import annotations

import base64

import numpy as np

from .base import InspectionTool, ToolResult
from .registry import register


def _gray(image) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        return arr[..., :3].mean(axis=2)
    return arr.astype(np.float32)


def _foreground(gray) -> np.ndarray:
    """Otsu binary with the object as the minority (foreground) class = 255."""
    import cv2

    g = gray.astype(np.uint8)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (b == 255).mean() > 0.5:
        b = 255 - b
    return b


@register
class PresenceTool(InspectionTool):
    """Presence / absence: pass when the object covers (or doesn't) the ROI.

    config: mode "present"|"absent" (default present); min_coverage 0..1 (0.05).
    """

    type = "presence"

    def inspect(self, roi_image) -> ToolResult:
        coverage = float((_foreground(_gray(roi_image)) > 0).mean())
        mode = self.config.get("mode", "present")
        min_cov = float(self.config.get("min_coverage", 0.05))
        present = coverage >= min_cov
        passed = present if mode == "present" else not present
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=f"{coverage * 100:.1f}% covered",
            expected_value=mode,
            confidence=coverage,
            model_version="presence",
            detail={"coverage": round(coverage, 4), "mode": mode},
        )


@register
class MeasureTool(InspectionTool):
    """Measure the object's width/height in the ROI and check it's within range.

    config: axis "width"|"height"; min_px; max_px; mm_per_pixel (optional).
    """

    type = "measure"

    def inspect(self, roi_image) -> ToolResult:
        binary = _foreground(_gray(roi_image))
        ys, xs = np.where(binary > 0)
        if xs.size == 0:
            return ToolResult(self.tool_id, False, "no object", "", 0.0, "measure", {})
        width = int(xs.max() - xs.min() + 1)
        height = int(ys.max() - ys.min() + 1)
        axis = self.config.get("axis", "width")
        value_px = width if axis == "width" else height
        mm_per_px = self.config.get("mm_per_pixel")
        lo = float(self.config.get("min_px", 0))
        hi = float(self.config.get("max_px", 10**9))
        passed = lo <= value_px <= hi
        if mm_per_px:
            shown = f"{value_px * float(mm_per_px):.2f} mm"
        else:
            shown = f"{value_px} px"
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=shown,
            expected_value=f"{lo:g}–{hi:g} px",
            confidence=1.0 if passed else 0.0,
            model_version="measure",
            detail={"value_px": value_px, "axis": axis},
        )


@register
class ColorTool(InspectionTool):
    """Colour check: pass when the ROI's mean colour is within tolerance of a
    target (e.g. correct cap/tablet colour).

    config: target [r,g,b]; tolerance (mean RGB distance, default 40).
    """

    type = "color_check"

    def inspect(self, roi_image) -> ToolResult:
        arr = np.asarray(roi_image)
        if arr.ndim != 3:
            arr = np.stack([arr] * 3, axis=-1)
        mean = arr[..., :3].reshape(-1, 3).mean(axis=0)
        target = np.asarray(self.config.get("target", [0, 0, 0]), dtype=np.float32)
        dist = float(np.linalg.norm(mean - target))
        tol = float(self.config.get("tolerance", 40))
        passed = dist <= tol
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=f"rgb({int(mean[0])},{int(mean[1])},{int(mean[2])})",
            expected_value=f"rgb({int(target[0])},{int(target[1])},{int(target[2])}) ±{tol:g}",
            confidence=max(0.0, 1.0 - dist / 441.0),
            model_version="color",
            detail={"distance": round(dist, 2)},
        )


def register_template(image) -> str:
    """Encode an ROI patch as a base64 grayscale golden template."""
    import cv2

    g = _gray(image).astype(np.uint8)
    ok, buf = cv2.imencode(".png", g)
    return base64.b64encode(buf.tobytes()).decode("ascii")


@register
class TemplateMatchTool(InspectionTool):
    """Golden-template compare: pass when the ROI matches a registered reference
    (normalised cross-correlation) — catches missing/garbled artwork or print.

    config: template (base64 grayscale); min_score 0..1 (default 0.6).
    """

    type = "template_match"

    def inspect(self, roi_image) -> ToolResult:
        import cv2

        template = self.config.get("template")
        if not template:
            return ToolResult(self.tool_id, False, "no template", "", 0.0, "template", {})
        arr = np.frombuffer(base64.b64decode(template), dtype=np.uint8)
        tpl = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        roi = _gray(roi_image).astype(np.uint8)
        roi = cv2.resize(roi, (tpl.shape[1], tpl.shape[0]), interpolation=cv2.INTER_AREA)
        a = roi.astype(np.float32) - roi.mean()
        b = tpl.astype(np.float32) - tpl.mean()
        denom = float(np.sqrt((a * a).sum()) * np.sqrt((b * b).sum()))
        score = float((a * b).sum() / denom) if denom else 0.0
        min_score = float(self.config.get("min_score", 0.6))
        return ToolResult(
            tool_id=self.tool_id,
            passed=score >= min_score,
            measured_value=f"match {score:.2f}",
            expected_value=f"≥ {min_score:.2f}",
            confidence=max(0.0, score),
            model_version="template-ncc",
            detail={"score": round(score, 3)},
        )
