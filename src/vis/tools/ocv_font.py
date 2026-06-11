"""Font-trained OCV (the pharma-standard approach to coding verification).

Instead of a generic OCR model, the operator REGISTERS the customer's actual
characters once (from a clear sample of the print). At runtime each ROI is
segmented into characters and every character is matched against the registered
font. Because the font is defined by the customer's own print, this reads styles
that generic OCR cannot — including CIJ/TIJ DOT-MATRIX codes (morphological
"dot-connect" merges the dots into glyphs before matching).

Config:
  font:           {char: [base64 PNG glyph, ...]}  — the registered font
  match/expected/pattern/field:  same semantics as OcrTextTool
  invert:         True/False/None(auto) — make text the foreground
  dot_kernel:     int — morphological close size to connect dot-matrix dots
  min_area:       int — ignore specks smaller than this (px)
  min_char_score: float — below this a character reads as '?'
"""

from __future__ import annotations

import base64
import re

import numpy as np

from .base import InspectionTool, ToolResult
from .ocr import _match_key
from .registry import register

NORM = (24, 32)  # normalized glyph size (w, h) for matching


# ---- image ops ------------------------------------------------------------
def _gray(image):
    import cv2

    arr = np.asarray(image)
    return cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr


def _binarize(gray, invert):
    import cv2

    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert is None:  # auto: text should be the (smaller) foreground = white
        if (b == 255).mean() > 0.5:
            b = 255 - b
    elif invert:
        b = 255 - b
    return b


def _dot_connect(binary, kernel):
    import cv2

    if kernel and kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(kernel), int(kernel)))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k)
    return binary


def _prepare_binary(gray, invert, dot_kernel):
    """The documented dot-matrix pipeline (US 5,212,741; modern equivalent):
    GREY-LEVEL spatial averaging smooths dots into strokes (kernel scaled to the
    dot pitch), contrast stretch, THEN binarize — far more stable than closing a
    noisy binary image. A small binary close still mops up residual gaps."""
    import cv2

    if dot_kernel and dot_kernel > 1:
        k = int(dot_kernel)
        gray = cv2.blur(gray, (k, k))
        gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype("uint8")
    binary = _binarize(gray, invert)
    return _dot_connect(binary, min(3, int(dot_kernel or 0)))


def _char_boxes(binary, min_area):
    import cv2

    n, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or h < 4 or w < 2:
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    boxes.sort(key=lambda b: b[0])
    return _merge_overlaps(boxes)


def _merge_overlaps(boxes):
    """Merge boxes that overlap heavily in x (e.g. an accent over a glyph)."""
    merged = []
    for b in boxes:
        if merged:
            px, py, pw, ph = merged[-1]
            overlap = min(px + pw, b[0] + b[2]) - max(px, b[0])
            if overlap > 0.6 * min(pw, b[2]):
                nx, ny = min(px, b[0]), min(py, b[1])
                nx2, ny2 = max(px + pw, b[0] + b[2]), max(py + ph, b[1] + b[3])
                merged[-1] = (nx, ny, nx2 - nx, ny2 - ny)
                continue
        merged.append(b)
    return merged


def _norm_glyph(binary, box):
    import cv2

    x, y, w, h = box
    glyph = binary[y : y + h, x : x + w]
    ys, xs = np.where(glyph > 0)  # tight-crop to the glyph's own ink so matching
    if xs.size:                    # is invariant to cell padding / position
        glyph = glyph[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    return cv2.resize(glyph, NORM, interpolation=cv2.INTER_AREA)


def _encode(glyph) -> str:
    import cv2

    ok, buf = cv2.imencode(".png", glyph)
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _decode(data) -> np.ndarray:
    import cv2

    arr = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)


def _ncc(a, b) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum()) * np.sqrt((b * b).sum()))
    return float((a * b).sum() / denom) if denom else 0.0


# ---- font registration + reading -----------------------------------------
def _split_boxes(binary, n_chars, min_area):
    """Character boxes. With a known count (verification) split the foreground
    bounding-box into n equal slices (coder fonts are monospace — far more robust
    than guessing boundaries). Otherwise fall back to connected components."""
    if n_chars and n_chars > 0:
        return _even_split(binary, n_chars)
    return _char_boxes(binary, min_area)


def register_font(image, text, font=None, invert=None, dot_kernel=0, min_area=10) -> dict:
    """Add the glyphs in `text` (the operator types what the sample says) to a
    font model. Returns {char: [base64 glyph, ...]} merging into `font`."""
    font = {k: list(v) for k, v in (font or {}).items()}
    binary = _prepare_binary(_gray(image), invert, dot_kernel)
    chars = [c for c in text if not c.isspace()]
    boxes = _even_split(binary, len(chars))  # text is known -> split by count
    for ch, box in zip(chars, boxes):
        font.setdefault(ch, []).append(_encode(_norm_glyph(binary, box)))
    return font


def _even_split(binary, n):
    """Split a tightly-framed string into n character boxes. Splits at the n-1
    widest inter-character GAPS (robust for monospace coder fonts) and falls back
    to equal slices if there aren't enough gaps."""
    ys, xs = np.where(binary > 0)
    if n <= 0 or xs.size == 0:
        return []
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    if n == 1:
        return [(x0, y0, x1 - x0 + 1, y1 - y0 + 1)]

    fg = (binary[y0 : y1 + 1, x0 : x1 + 1] > 0).sum(axis=0) > 0
    gaps = []  # (center, width) of zero-runs between characters
    i = 0
    width = fg.size
    while i < width:
        if not fg[i]:
            j = i
            while j < width and not fg[j]:
                j += 1
            gaps.append((x0 + (i + j) // 2, j - i))
            i = j
        else:
            i += 1
    seps = sorted(c for c, _ in sorted(gaps, key=lambda g: -g[1])[: n - 1])
    if len(seps) < n - 1:  # not enough gaps -> equal slices
        step = (x1 - x0 + 1) / n
        return [(int(x0 + i * step), y0, max(1, int(round(step))), y1 - y0 + 1) for i in range(n)]
    bounds = [x0] + seps + [x1 + 1]
    return [(bounds[k], y0, max(1, bounds[k + 1] - bounds[k]), y1 - y0 + 1) for k in range(n)]


def _filter_charset(font: dict, charset: str | None) -> dict:
    """Vendor-documented lexicon constraining: restrict candidate characters to
    what the field can contain (digits-only dates, etc.)."""
    if not charset:
        return font
    allowed = {
        "digits": set("0123456789"),
        "letters": set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        "alnum": set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    }.get(charset)
    if allowed is None:
        allowed = set(charset.upper())  # explicit set, e.g. "0123456789./"
    return {ch: tpls for ch, tpls in font.items() if ch in allowed} or font


def read_text(image, font, n_chars=None, invert=None, dot_kernel=0, min_area=10,
              min_char_score=0.3, charset=None):
    """Read text using the registered `font`. If `n_chars` is known (we're
    verifying a value of known length) the ROI is split by count. Returns
    (text, mean_score)."""
    if not font:
        return "", 0.0
    templates = _filter_charset(font, charset)
    templates = {ch: [_decode(t) for t in tpls] for ch, tpls in templates.items()}
    binary = _prepare_binary(_gray(image), invert, dot_kernel)
    out = []
    scores = []
    for box in _split_boxes(binary, n_chars, min_area):
        glyph = _norm_glyph(binary, box)
        best_ch, best_s = "?", -1.0
        for ch, tpls in templates.items():
            for tpl in tpls:
                s = _ncc(glyph, tpl)
                if s > best_s:
                    best_s, best_ch = s, ch
        out.append(best_ch if best_s >= min_char_score else "?")
        scores.append(max(0.0, best_s))
    return "".join(out), (sum(scores) / len(scores) if scores else 0.0)


def verify_text(image, font, expected, invert=None, dot_kernel=0, min_char_score=0.5,
                margin=0.05):
    """OCV verification: split the print into len(expected) characters and score
    each position against the EXPECTED character's templates only. Returns
    (readback, mean_score, char_scores) where readback shows the expected char
    where it verified and '?' where it didn't."""
    chars = [c for c in expected.upper() if not c.isspace()]
    if not chars or not font:
        return "", 0.0, []
    binary = _prepare_binary(_gray(image), invert, dot_kernel)
    boxes = _even_split(binary, len(chars))
    if len(boxes) != len(chars):
        return "", 0.0, [0.0] * len(chars)
    templates = {ch: [_decode(t) for t in tpls] for ch, tpls in font.items()}
    readback = []
    scores = []
    for ch, box in zip(chars, boxes):
        glyph = _norm_glyph(binary, box)
        best = max((_ncc(glyph, tpl) for tpl in templates.get(ch, [])), default=0.0)
        # OCVMax-style confusion gate: the expected character must also BEAT the
        # best-scoring OTHER character by `margin` (top-1 minus top-2) — catches
        # a misprint that resembles the expected glyph but matches another more.
        best_other = 0.0
        for other, tpls in templates.items():
            if other == ch:
                continue
            score_other = max((_ncc(glyph, tpl) for tpl in tpls), default=0.0)
            best_other = max(best_other, score_other)
        ok = best >= min_char_score and (best - best_other) >= margin
        scores.append(max(0.0, best))
        readback.append(ch if ok else "?")
    return "".join(readback), (sum(scores) / len(scores)), scores


@register
class FontOcvTool(InspectionTool):
    """Font-trained OCV text verification (handles dot-matrix / customer fonts)."""

    type = "ocv_font"

    def inspect(self, roi_image) -> ToolResult:
        cfg = self.config
        _legacy = int(cfg.get("search_margin", 0) or 0)
        if int(cfg.get("search_x", _legacy) or 0) > 0 or int(cfg.get("search_y", _legacy) or 0) > 0:
            from .transform import locate_text_band

            roi_image = locate_text_band(roi_image, prefer=cfg.get("_inner_roi"))
        expected_str = cfg.get("expected") or ""
        n_chars = len([c for c in expected_str if not c.isspace()]) or None
        char_scores: list[float] = []
        if cfg.get("match", "exact") == "exact" and expected_str and cfg.get("font"):
            # TRUE OCV: verify each character position against the EXPECTED
            # character's templates (never classify across the whole font — no
            # "irrelevant" reads; either the print matches or it doesn't).
            text, score, char_scores = verify_text(
                roi_image,
                cfg["font"],
                expected_str,
                invert=cfg.get("invert"),
                dot_kernel=cfg.get("dot_kernel", 0),
                min_char_score=cfg.get("min_char_score", 0.5),
                margin=cfg.get("char_margin", 0.05),
            )
        else:
            text, score = read_text(
                roi_image,
                cfg.get("font") or {},
                n_chars=n_chars,
                invert=cfg.get("invert"),
                dot_kernel=cfg.get("dot_kernel", 0),
                min_area=cfg.get("min_area", 10),
                min_char_score=cfg.get("min_char_score", 0.45),
                charset=cfg.get("charset"),
            )
        measured = text.strip()
        mode = cfg.get("match", "exact")
        expected = cfg.get("expected")
        if mode == "regex":
            passed = bool(re.fullmatch(cfg.get("pattern", ""), measured))
            expected_display = cfg.get("pattern", "")
        elif mode == "batch_field":
            passed = bool(_match_key(measured))
            expected_display = f"[batch field: {cfg.get('field', '')}]"
        elif mode == "contains":
            key_e = _match_key(expected or "")
            passed = bool(key_e) and key_e in _match_key(measured)
            expected_display = expected
        else:
            passed = _match_key(measured) == _match_key(expected or "")
            expected_display = expected
        if "?" in measured:  # an unrecognised character -> not a confident read
            passed = passed and "?" not in measured
        return ToolResult(
            tool_id=self.tool_id,
            passed=passed,
            measured_value=measured,
            expected_value=expected_display,
            confidence=score,
            model_version="font-ocv",
            detail={
                "match": mode,
                "char_score": round(score, 3),
                "char_scores": [round(v, 2) for v in char_scores],
            },
        )
