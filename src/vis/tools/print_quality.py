"""Per-character PRINT-QUALITY grading for OCV — the Omron/Visionscape metric
family (contrast, stroke-width consistency, dropout/fragmentation, sharpness,
position), graded in ISO-15415-style A–F bands. Distinguishes "badly printed
but correct" from "wrong text" (pair with the reader's verify_expected).

Template-free: segments characters from the line crop and computes intrinsic
quality metrics — no golden sample needed (a variation-model golden compare can
be layered later). Parameters follow ISO 1831 / NIST FIPS 90 print-quality
factors (stroke width, contrast, voids, character positioning).

    from vis.tools.print_quality import grade_line
    report = grade_line(gray_line_crop)
    report["grade"]      # 'A'..'F' overall (worst char governs, ISO-style)
    report["chars"]      # per-char dicts with metrics + grade
"""
from __future__ import annotations

import numpy as np

GRADES = "ABCDF"


def _to_gray(image) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = arr[..., :3].mean(axis=2)
    return arr.astype(np.float32)


def _segment_chars(gray: np.ndarray):
    """Character cells via ink column-projection on the Otsu-binarised line."""
    import cv2

    g = cv2.GaussianBlur(gray.astype(np.uint8), (3, 3), 0)
    _, binary = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = binary == 0 if (binary == 255).mean() > 0.5 else binary == 255
    cols = ink.sum(axis=0)
    if cols.max() == 0:
        return ink, []
    active = cols > max(1, 0.06 * cols.max())
    cells, st = [], None
    for i, on in enumerate(active):
        if on and st is None:
            st = i
        elif not on and st is not None:
            if i - st >= 3:
                cells.append((st, i))
            st = None
    if st is not None:
        cells.append((st, len(active)))
    # merge cells separated by tiny gaps (broken glyphs shouldn't split cells)
    merged = []
    med_w = np.median([b - a for a, b in cells]) if cells else 0
    for a, b in cells:
        if merged and a - merged[-1][1] <= max(1, 0.15 * med_w):
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return ink, merged


def _char_metrics(gray: np.ndarray, ink: np.ndarray, x0: int, x1: int) -> dict:
    import cv2

    sub_ink = ink[:, x0:x1]
    sub_gray = gray[:, x0:x1]
    ys, xs = np.where(sub_ink)
    if ys.size < 5:
        return {"empty": True}
    y0, y1 = ys.min(), ys.max() + 1
    cell_ink = sub_ink[y0:y1]
    cell_gray = sub_gray[y0:y1]

    # contrast: ink vs paper grey levels within the cell (ISO 1831 print contrast)
    ink_med = float(np.median(cell_gray[cell_ink]))
    paper = cell_gray[~cell_ink]
    paper_med = float(np.median(paper)) if paper.size else 255.0
    contrast = max(0.0, (paper_med - ink_med)) / max(1.0, paper_med)

    # stroke width via distance transform: mean*2 and coefficient of variation
    dist = cv2.distanceTransform(cell_ink.astype(np.uint8), cv2.DIST_L2, 3)
    core = dist[dist > 0.5]
    stroke_w = float(2 * core.mean()) if core.size else 0.0
    stroke_cv = float(core.std() / core.mean()) if core.size and core.mean() > 0 else 1.0

    # dropout/fragmentation: pieces per glyph + ink density inside the glyph hull
    n_comp, _ = cv2.connectedComponents(cell_ink.astype(np.uint8), connectivity=8)
    fragments = int(n_comp - 1)

    # sharpness: gradient magnitude across the ink boundary, normalised by contrast
    gx = cv2.Sobel(cell_gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(cell_gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.sqrt(gx * gx + gy * gy)
    edge = cv2.morphologyEx(cell_ink.astype(np.uint8), cv2.MORPH_GRADIENT,
                            np.ones((3, 3), np.uint8)) > 0
    sharp = float(mag[edge].mean() / max(1.0, paper_med - ink_med)) if edge.any() else 0.0

    return {
        "empty": False, "x0": int(x0), "x1": int(x1),
        "top": int(y0), "bottom": int(y1),
        "contrast": round(contrast, 3),
        "stroke_width_px": round(stroke_w, 2),
        "stroke_cv": round(stroke_cv, 3),
        "fragments": fragments,
        "sharpness": round(sharp, 3),
        "coverage": round(float(cell_ink.mean()), 3),   # ink fraction of glyph bbox
    }


def _grade_char(m: dict, med_stroke: float, baseline: float, height: float,
                style: str = "solid") -> str:
    """A–F from the worst individual factor (ISO-grading convention)."""
    if m.get("empty"):
        return "F"
    scores = []
    # contrast bands (ISO 1831 wants "high contrast"; foil grey-on-grey ~0.45-0.5
    # is good real-world print — bands calibrated on real blister crops)
    c = m["contrast"]
    scores.append(0 if c >= 0.45 else 1 if c >= 0.32 else 2 if c >= 0.22 else 3 if c >= 0.14 else 4)
    # stroke consistency (distance-transform CV ~0.5-0.6 is normal for solid
    # glyphs with junctions; degradation pushes it up)
    scores.append(0 if m["stroke_cv"] <= 0.62 else 1 if m["stroke_cv"] <= 0.75
                  else 2 if m["stroke_cv"] <= 0.90 else 3 if m["stroke_cv"] <= 1.10 else 4)
    # fragmentation: solid print should be 1 piece/glyph (voids sever strokes);
    # dot-matrix (style="dot") legitimately fragments, so bands are loose there
    f = m["fragments"]
    if style == "dot":
        scores.append(0 if f <= 12 else 1 if f <= 18 else 2 if f <= 25 else 3 if f <= 35 else 4)
    else:
        scores.append(0 if f <= 1 else 1 if f <= 2 else 2 if f <= 3 else 3 if f <= 5 else 4)
    # stroke width deviation vs line median (fade/smear both move it)
    if med_stroke > 0:
        dev = abs(m["stroke_width_px"] - med_stroke) / med_stroke
        scores.append(0 if dev <= 0.25 else 1 if dev <= 0.4 else 2 if dev <= 0.6
                      else 3 if dev <= 0.85 else 4)
    # vertical position vs baseline (registration)
    if height > 0:
        drift = abs(m["bottom"] - baseline) / height
        scores.append(0 if drift <= 0.08 else 1 if drift <= 0.15 else 2 if drift <= 0.25
                      else 3 if drift <= 0.4 else 4)
    return GRADES[max(scores)]


def grade_line(image, reference: dict | None = None, style: str = "solid") -> dict:
    """Grade one text-line crop. Returns {'grade', 'chars': [...], 'n_chars'}.

    `reference` (optional) = the TAUGHT-time signature of a known-good sample,
    e.g. ``{"median_stroke_px": 8.1}`` from grading the golden crop at teach.
    With it, uniform smear/fade (which shifts the whole line and so evades the
    own-median comparison) is caught by line-vs-reference stroke deviation."""
    gray = _to_gray(image)
    ink, cells = _segment_chars(gray)
    chars = [_char_metrics(gray, ink, a, b) for a, b in cells]
    real = [c for c in chars if not c.get("empty")]
    med_stroke = float(np.median([c["stroke_width_px"] for c in real])) if real else 0.0
    baseline = float(np.median([c["bottom"] for c in real])) if real else 0.0
    height = float(np.median([c["bottom"] - c["top"] for c in real])) if real else 0.0
    ref_score = 0
    if reference and reference.get("median_stroke_px") and med_stroke:
        dev = abs(med_stroke - reference["median_stroke_px"]) / reference["median_stroke_px"]
        ref_score = (0 if dev <= 0.20 else 1 if dev <= 0.35 else 2 if dev <= 0.55
                     else 3 if dev <= 0.80 else 4)
    for c in chars:
        g = _grade_char(c, med_stroke, baseline, height, style)
        c["grade"] = GRADES[max(GRADES.index(g), ref_score)]
    worst = max((GRADES.index(c["grade"]) for c in chars), default=len(GRADES) - 1)
    return {"grade": GRADES[worst], "n_chars": len(chars), "chars": chars,
            "median_stroke_px": med_stroke}
