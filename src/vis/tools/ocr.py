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
        # Line-PC acceleration: with onnxruntime-gpu installed, VIS_OCR_CUDA=1
        # runs det/cls/rec on the GPU (rapidocr 1.2.x supports the CUDA EP only;
        # OpenVINO needs a newer rapidocr or a licensed engine via the reader seam).
        if os.environ.get("VIS_OCR_CUDA", "").lower() in ("1", "true", "yes"):
            kwargs.update(det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True)
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


# Visually-confusable characters folded for VERIFICATION (both sides get the
# same folding, so it stays consistent): printed "B.No." read as "B.N0." must
# not reject. Standard OCV practice for coded text (lot/exp/MRP).
_CONFUSABLES = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "Z": "2"})


def _match_key(s: str) -> str:
    """Comparison key: upper-case alphanumerics only (spaces + punctuation
    ignored) with confusable characters folded (O→0, I/L→1, S→5, Z→2), so an
    OCR slip on a lookalike glyph or a '.'/',' never causes a false reject.
    The raw read is still shown to the operator."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum()).translate(_CONFUSABLES)


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


def _run_rec_only(engine, image) -> tuple[str, float]:
    """Recognition directly on the whole crop (no detector) — the right primary
    path for a fixed, operator-drawn single-line ROI: faster, and immune to the
    detector fragmenting a tight crop into partial reads."""
    try:
        result, _ = engine(image, use_det=False, use_rec=True)
    except Exception:
        return "", 0.0
    if not result:
        return "", 0.0
    # rapidocr's rec-only items are [text, score] (2-tuple); some versions
    # carry a leading box as [box, text, score]. The score is always last and
    # the text immediately precedes it — index from the end to support both.
    texts = [str(item[-2]) for item in result]
    scores = [float(item[-1]) for item in result]
    return " ".join(texts).strip(), (sum(scores) / len(scores))


def _run_det_rec(engine, image) -> tuple[str, float]:
    """Full detect + recognise (for multi-line / loose boxes), reading order."""
    result, _ = engine(image)
    if not result:
        return "", 0.0
    items = _reading_order(result)
    texts = [item[1] for item in items]
    scores = [float(item[2]) for item in items]
    return " ".join(texts).strip(), (sum(scores) / len(scores))


def _metric(text: str, score: float) -> float:
    return len(text.replace(" ", "")) * max(score, 0.01)


def _prepare_variants(image) -> list:
    """Several preprocessed RGB variants of an ROI — the reader OCRs each and keeps
    the read that resolves. Industrial OCV (Cognex/Keyence) reads by transforming
    the crop into whichever representation makes the text fully visible; no single
    filter wins across glare/foil/security-mesh/faint print, so we offer a panel:
    contrast-normalised, denoised, illumination-flattened, locally-thresholded,
    glare-clipped and background-flattened. Variant 0 is the proven default."""
    import numpy as np

    arr = _pad(image, 6)
    try:
        import cv2
    except Exception:
        return [arr]
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h = gray.shape[0]
    target = 140  # PP-OCR reads small text far better enlarged to ~this height
    if 0 < h < target:
        factor = min(4.0, target / h)
        gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    out = []
    # 1. contrast-normalised — proven default for clean print
    out.append(clahe.apply(gray) if gray.std() < 55 else gray)
    # 2. edge-preserving denoise + normalise — security-mesh / speckle
    out.append(clahe.apply(cv2.bilateralFilter(gray, 7, 60, 60)))
    # 3. illumination-flattened — divide by a large blur to even out glare/foil
    #    gradients and specular fall-off (flat-field / homomorphic style)
    sigma = max(3.0, gray.shape[0] / 3.0)
    blur = cv2.GaussianBlur(gray, (0, 0), sigma).astype(np.float32) + 1.0
    flat = cv2.normalize(gray.astype(np.float32) / blur, None, 0, 255, cv2.NORM_MINMAX)
    out.append(clahe.apply(flat.astype(np.uint8)))
    # 4. local adaptive threshold — robust to uneven lighting / specular glare
    bs = max(11, (gray.shape[0] // 2) | 1)
    out.append(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                     cv2.THRESH_BINARY, bs, 9))
    # 5. glare-clipped — pull specular highlights down to the 95th percentile,
    #    then stretch contrast so text under near-saturation reappears
    cap = max(1, int(np.percentile(gray, 95)))
    clipped = cv2.normalize(np.clip(gray, 0, cap), None, 0, 255, cv2.NORM_MINMAX)
    out.append(clahe.apply(clipped.astype(np.uint8)))
    # 6. background-flattened black-hat — dark print on a busy/textured background
    ksize = max(9, (gray.shape[0] // 3) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    out.append(cv2.subtract(255, cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)))
    return [cv2.cvtColor(np.asarray(v, dtype=np.uint8), cv2.COLOR_GRAY2RGB) for v in out]


def recognize(roi_image, accept=None) -> tuple[str, float]:
    """Return (text, mean_confidence) for a cropped ROI.

    `accept(text) -> bool` (optional) marks a read as the expected one (used for
    VERIFICATION, where we know what the field should say). When given, every
    transform is tried until the text resolves through glare/reflection and a
    confident accepted read wins — a transform can't fabricate a match, so this
    is safe. Without it (pure reading) the proven primary read is kept and the
    extra transforms only act as a last resort when nothing was read."""
    engine = _engine()
    variants = _prepare_variants(roi_image)
    primary = variants[0] if variants else _pad(roi_image, 6)
    text, score = _run_rec_only(engine, primary)
    if score >= 0.85 and len(text.replace(" ", "")) >= 2 and (accept is None or accept(text)):
        return text, score
    best = (text, score)
    try:  # a detector pass on the primary (multi-line / loose boxes)
        t2, s2 = _run_det_rec(engine, primary)
        if _metric(t2, s2) > _metric(*best):
            best = (t2, s2)
    except Exception:
        pass

    if accept is not None:
        # verification: the primary already reads the expected → done
        if accept(best[0]) and best[1] >= 0.5:
            return best
        # otherwise try every transform; collect confident reads that match the
        # expected and return the most confident one (glare often clears in only
        # one representation). Never below a confidence floor, so noise can't pass.
        accepted = [best] if (accept(best[0]) and best[1] >= 0.4) else []
        for image in variants[1:]:
            t, s = _run_rec_only(engine, image)
            if t and s >= 0.4 and accept(t):
                accepted.append((t, s))
        if accepted:
            return max(accepted, key=lambda c: c[1])
        # nothing matched — return the plain primary read so it stays "weak" and
        # the tool's orientation search still fires (a fat garbage read would not)
        return text, score

    # pure reading: keep a usable primary read; only if nothing was read fall back
    # to the cleanup/glare transforms (never override a real read).
    if len(best[0].replace(" ", "")) >= 2:
        return best
    for image in variants[1:]:
        t, s = _run_rec_only(engine, image)
        if len(t.replace(" ", "")) >= 2 and _metric(t, s) > _metric(*best):
            best = (t, s)
    return best


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

        from .readers import get_text_reader

        reader = get_text_reader(self.config.get("reader"))
        rotation = self.config.get("rotation", 0)
        roi = rotate_image(roi_image, rotation)
        _legacy = int(self.config.get("search_margin", 0) or 0)
        if int(self.config.get("search_x", _legacy) or 0) > 0 or int(self.config.get("search_y", _legacy) or 0) > 0:
            # outer search window -> locate the line anchored on the taught
            # inner box (stable regardless of margin size)
            from .transform import locate_text_band

            inner = None if rotation else self.config.get("_inner_roi")
            roi = locate_text_band(roi, prefer=inner)
        text, score = reader(roi, self.config)
        # Only search orientations when the straight read is WEAK (empty / a few
        # chars / low confidence) — otherwise we'd risk "improving" a good read
        # into a 180°-flipped one. For reliable reading, orient the image upright
        # (Rotate image) or set an explicit Rotation.
        weak = (not text) or (len(text.replace(" ", "")) < 3) or (score < 0.4)
        if not rotation and weak:
            key_expected = _match_key(self.config.get("expected") or "")

            def _matches(t):  # does this read contain the expected value?
                return bool(key_expected) and key_expected in _match_key(_normalize(t, self.config))

            def _metric(t, s):
                return len(t.replace(" ", "")) * max(s, 0.01)

            best_text, best_score = text, score
            for extra in (90, 180, 270):
                t2, s2 = reader(rotate_image(roi, extra), self.config)
                # prefer an orientation whose read MATCHES the expected value;
                # among equal matches fall back to the length-weighted metric
                better = (_matches(t2) and not _matches(best_text)) or (
                    _matches(t2) == _matches(best_text)
                    and _metric(t2, s2) > _metric(best_text, best_score)
                )
                if better:
                    best_text, best_score = t2, s2
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
