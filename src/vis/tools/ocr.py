"""OCR/OCV text verification via ONNX PaddleOCR (RapidOCR / PP-OCR).

Verifies printed text fields (lot, expiry, MRP) against an expected value or a
format pattern. The engine (RapidOCR, PP-OCR models on ONNX Runtime) is loaded
lazily, once per process, and cached — mirroring the warm-session design in
docs/05. The dependency is optional (pip install '.[ocr]').

Throughput note: this uses the full det+rec pipeline for robustness. The
recognition-only + INT8 mobile fast path (docs/05) is the production
throughput optimisation.
"""

from __future__ import annotations

import re

from .base import InspectionTool, ToolResult
from .registry import register

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "OCR engine not installed. Install it with: pip install '.[ocr]'"
            ) from exc
        _ENGINE = RapidOCR()
    return _ENGINE


def recognize(roi_image) -> tuple[str, float]:
    """Return (text, mean_confidence) for a cropped ROI image."""
    result, _ = _engine()(roi_image)
    if not result:
        return "", 0.0
    texts = [item[1] for item in result]
    scores = [float(item[2]) for item in result]
    return " ".join(texts).strip(), (sum(scores) / len(scores))


def _normalize(text: str, config: dict) -> str:
    if config.get("strip", True):
        text = text.strip()
    if config.get("uppercase", False):
        text = text.upper()
    if config.get("ignore_spaces", False):
        text = text.replace(" ", "")
    return text


@register
class OcrTextTool(InspectionTool):
    """OCV text tool.

    Config:
      expected:        str  — value to match (exact/contains modes)
      match:           "exact" (default) | "contains" | "regex"
      pattern:         str  — regex for `match="regex"` (e.g. date format)
      uppercase:       bool — normalise case before comparing
      ignore_spaces:   bool — strip internal spaces before comparing
      min_confidence:  float — fail if OCR confidence below this
    """

    type = "ocv_text"

    def inspect(self, roi_image) -> ToolResult:
        text, score = recognize(roi_image)
        measured = _normalize(text, self.config)
        mode = self.config.get("match", "exact")
        expected = self.config.get("expected")

        if mode == "regex":
            pattern = self.config.get("pattern", "")
            passed = bool(re.fullmatch(pattern, measured))
            expected_display = pattern
        elif mode == "contains":
            passed = bool(expected) and expected in measured
            expected_display = expected
        else:
            passed = measured == expected
            expected_display = expected

        if score < float(self.config.get("min_confidence", 0.0)):
            passed = False

        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=measured,
            expected_value=expected_display,
            confidence=score,
            model_version="rapidocr-ppocr",
            detail={"ocr_confidence": round(score, 3), "match": mode},
        )
