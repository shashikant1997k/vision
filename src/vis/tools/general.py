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

    config:
        template     base64 grayscale reference
        min_score    0..1 (default 0.6)
        angle_range  ± degrees to search (default 0 = no rotation search). Use
                     this when the part can sit skewed on the conveyor: without
                     it a good part rotated a few degrees scores low and is
                     wrongly rejected.
        angle_step   search granularity in degrees (default 2)
        allow_inverted  accept reversed polarity — white-on-black artwork
                     matches a black-on-white template (default False). NCC of an
                     inverted image is the negative of the score, so this simply
                     scores on the magnitude.

    The best angle is reported in ``detail`` — a part that consistently matches
    at +6° is telling you the fixture has drifted.
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

        b = tpl.astype(np.float32) - tpl.mean()
        b_norm = float(np.sqrt((b * b).sum()))
        allow_inverted = bool(self.config.get("allow_inverted", False))

        def ncc(candidate: np.ndarray) -> float:
            a = candidate.astype(np.float32) - candidate.mean()
            denom = float(np.sqrt((a * a).sum()) * b_norm)
            if not denom:
                return 0.0
            value = float((a * b).sum() / denom)
            return abs(value) if allow_inverted else value

        score, best_angle = ncc(roi), 0.0
        angle_range = abs(float(self.config.get("angle_range", 0) or 0))
        if angle_range:
            step = abs(float(self.config.get("angle_step", 2) or 2)) or 2.0
            centre = (roi.shape[1] / 2.0, roi.shape[0] / 2.0)
            angle = -angle_range
            while angle <= angle_range + 1e-9:
                if angle:  # 0 is already scored
                    matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
                    rotated = cv2.warpAffine(
                        roi, matrix, (roi.shape[1], roi.shape[0]),
                        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
                    )
                    candidate = ncc(rotated)
                    if candidate > score:
                        score, best_angle = candidate, angle
                angle += step

        min_score = float(self.config.get("min_score", 0.6))
        detail = {"score": round(score, 3)}
        if angle_range:
            detail["angle"] = round(best_angle, 2)
        measured = f"match {score:.2f}"
        if angle_range and best_angle:
            measured += f" at {best_angle:+.1f}°"
        return ToolResult(
            tool_id=self.tool_id,
            passed=score >= min_score,
            measured_value=measured,
            expected_value=f"≥ {min_score:.2f}",
            confidence=max(0.0, score),
            model_version="template-ncc",
            detail=detail,
        )
