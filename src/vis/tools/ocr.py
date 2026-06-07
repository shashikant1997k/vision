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


def _default_model_dir():
    """First directory that holds PP-OCRv4 det.onnx + rec.onnx, or None.
    Looked up: $VIS_OCR_MODEL_DIR, ~/.vision-inspection/models/ppocrv4, repo models/."""
    import os
    from pathlib import Path

    candidates = []
    if os.environ.get("VIS_OCR_MODEL_DIR"):
        candidates.append(Path(os.environ["VIS_OCR_MODEL_DIR"]))
    candidates.append(Path.home() / ".vision-inspection" / "models" / "ppocrv4")
    candidates.append(Path(__file__).resolve().parents[3] / "models" / "ppocrv4")
    for directory in candidates:
        if (directory / "det.onnx").exists() and (directory / "rec.onnx").exists():
            return directory
    return None


def _engine():
    """Lazily build the OCR engine. Prefers PP-OCRv4 models if present (much more
    accurate than the bundled PP-OCRv3 mobile); falls back to the bundled model.
    Override per-file with VIS_OCR_DET_MODEL / VIS_OCR_REC_MODEL / VIS_OCR_CLS_MODEL."""
    global _ENGINE
    if _ENGINE is None:
        import os

        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "OCR engine not installed. Install it with: pip install '.[ocr]'"
            ) from exc
        det = os.environ.get("VIS_OCR_DET_MODEL")
        rec = os.environ.get("VIS_OCR_REC_MODEL")
        cls = os.environ.get("VIS_OCR_CLS_MODEL")
        if not (det and rec):
            directory = _default_model_dir()
            if directory is not None:
                det = det or str(directory / "det.onnx")
                rec = rec or str(directory / "rec.onnx")
        kwargs = {}
        if det:
            kwargs["det_model_path"] = det
        if rec:
            kwargs["rec_model_path"] = rec
        if cls:
            kwargs["cls_model_path"] = cls
        try:
            _ENGINE = RapidOCR(**kwargs) if kwargs else RapidOCR()
        except Exception:  # pragma: no cover - bad override path
            _ENGINE = RapidOCR()
    return _ENGINE


def _pad(image, border: int):
    import numpy as np

    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=2)
    arr = arr[..., :3]
    h, w = arr.shape[:2]
    out = np.full((h + 2 * border, w + 2 * border, 3), 255, dtype=np.uint8)
    out[border : border + h, border : border + w] = arr
    return out


def _prepare(image):
    """Preprocess an ROI for reliable OCR: pad for detector margin, upscale small
    crops (PP-OCR reads small text/punctuation far better when enlarged), convert
    to grayscale and normalise contrast (CLAHE) for low-contrast / foil prints.

    NB: binarisation (Otsu/adaptive) is intentionally NOT done — PP-OCR is trained
    on natural images and binarising measurably loses thin glyphs like '.'.
    """
    import numpy as np

    arr = _pad(image, 6)  # small margin only — large padding splits detection
    target = 140
    try:
        import cv2

        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        h = gray.shape[0]
        if 0 < h < target:
            factor = min(4.0, target / h)
            gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
        if gray.std() < 55:  # only normalise genuinely low-contrast / foil prints
            gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    except Exception:
        # OpenCV missing — fall back to a plain PIL upscale
        h = arr.shape[0]
        if 0 < h < target:
            from PIL import Image

            factor = min(4.0, target / h)
            size = (max(1, int(arr.shape[1] * factor)), max(1, int(h * factor)))
            arr = np.array(Image.fromarray(arr).resize(size, Image.LANCZOS), dtype=np.uint8)
        return arr


def _match_key(s: str) -> str:
    """Comparison key: upper-case alphanumerics only (spaces + punctuation
    ignored), so a '.'/',' OCR slip or a missing dot does not cause a false
    reject. The raw read (with punctuation) is still shown to the operator."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _reading_order(result):
    """Sort detected text boxes into reading order: cluster boxes into lines by
    vertical position, then order each line left-to-right (RapidOCR doesn't
    guarantee order, which otherwise scrambles words)."""
    boxes = []
    for item in result:
        box = item[0]
        try:
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            center_y = (min(ys) + max(ys)) / 2
            boxes.append([center_y, min(xs), max(ys) - min(ys), item])
        except Exception:
            boxes.append([0.0, 0.0, 1.0, item])
    if not boxes:
        return result
    avg_h = sum(b[2] for b in boxes) / len(boxes) or 1
    threshold = avg_h * 0.7
    boxes.sort(key=lambda b: b[0])  # by vertical centre
    lines: list = []
    for b in boxes:
        if lines and abs(b[0] - lines[-1][0]) <= threshold:
            lines[-1][1].append(b)
        else:
            lines.append([b[0], [b]])
    ordered = []
    for _, line in lines:
        line.sort(key=lambda b: b[1])  # left to right within the line
        ordered.extend(b[3] for b in line)
    return ordered


def recognize(roi_image) -> tuple[str, float]:
    """Return (text, mean_confidence) for a cropped ROI image. Pads the crop so
    the detector has margin, reads pieces in reading order, and falls back to
    whole-crop recognition (so a tight single-line box still reads)."""
    engine = _engine()
    image = _prepare(roi_image)
    result, _ = engine(image)
    if not result:
        try:
            result, _ = engine(image, use_det=False, use_rec=True)
        except Exception:
            result = None
    if not result:
        return "", 0.0
    items = _reading_order(result)
    texts = [item[1] for item in items]
    scores = [float(item[2]) for item in items]
    return " ".join(texts).strip(), (sum(scores) / len(scores))


def _normalize(text: str, config: dict) -> str:
    if config.get("strip", True):
        text = text.strip()
    text = " ".join(text.split())  # collapse runs of whitespace
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
        from .transform import rotate_image

        rotation = self.config.get("rotation", 0)
        roi = rotate_image(roi_image, rotation)
        text, score = recognize(roi)
        # Only search orientations when the straight read is WEAK (empty / a few
        # chars / low confidence) — otherwise we'd risk "improving" a good read
        # into a 180°-flipped one. For reliable reading, orient the image upright
        # (Rotate image) or set an explicit Rotation.
        weak = (not text) or (len(text.replace(" ", "")) < 3) or (score < 0.4)
        if not rotation and weak:

            def _metric(t, s):
                return len(t.replace(" ", "")) * max(s, 0.01)

            best_text, best_score, best = text, score, _metric(text, score)
            for extra in (90, 180, 270):
                t2, s2 = recognize(rotate_image(roi, extra))
                if _metric(t2, s2) > best:
                    best_text, best_score, best = t2, s2, _metric(t2, s2)
            text, score = best_text, best_score
        # `measured` is the raw read shown to the operator (keeps punctuation);
        # matching is done on alphanumeric keys so a '.'/',' OCR slip, a missing
        # dot, or extra spaces never causes a false reject.
        measured = _normalize(text, self.config)
        mode = self.config.get("match", "exact")
        expected = self.config.get("expected")

        if mode == "regex":
            pattern = self.config.get("pattern", "")
            passed = bool(re.fullmatch(pattern, measured))
            expected_display = pattern
        elif mode == "batch_field":
            # unresolved batch field (e.g. during teach Test): pass if any text read.
            # At batch run the recipe is resolved to a concrete contains-match.
            passed = bool(_match_key(measured))
            expected_display = f"[batch field: {self.config.get('field', '')}]"
        elif mode == "contains":
            key_e = _match_key(expected or "")
            passed = bool(key_e) and key_e in _match_key(measured)
            expected_display = expected
        else:  # exact
            passed = _match_key(measured) == _match_key(expected or "")
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
