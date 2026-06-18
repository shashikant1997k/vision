"""Auto-train an OCV font from real sample images (docs/11).

OCV only reads accurately when its per-character templates come from the ACTUAL
print. This bootstraps that from a folder of line photos: PP-OCR locates and
reads each text line, each detected line is matched to a KNOWN expected string
(so labels are correct even where OCR slips, e.g. 0/O), the line is cropped and
segmented into per-character glyphs, and the glyphs accumulate into a font model
across many images for robustness. The result is registered into the font
library and used by the teach "Verify Text (OCV)" tool.
"""

from __future__ import annotations

import numpy as np

from .ocr import _match_key
from .ocv_font import register_font


def _ocr_lines(image) -> list[tuple[str, tuple[int, int, int, int]]]:
    """Detected text lines as (text, (y0, y1, x0, x1)) on the given image."""
    from .ocr import _engine

    result, _ = _engine()(np.asarray(image))
    lines = []
    for item in result or []:
        box, text, score = item[0], item[1], float(item[2])
        if score < 0.4 or not text.strip():
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        lines.append((text, (int(min(ys)), int(max(ys)), int(min(xs)), int(max(xs)))))
    return lines


def _best_line(target: str, lines: list, used: set):
    """Pick the detected line whose text best matches `target` (confusable-folded
    overlap), not already consumed. Returns (index, box) or (None, None)."""
    tkey = _match_key(target)
    best_i, best_score = None, 0.0
    for i, (text, _box) in enumerate(lines):
        if i in used:
            continue
        lkey = _match_key(text)
        if not lkey:
            continue
        # character-overlap ratio (order-independent, robust to OCR noise)
        common = sum((min(tkey.count(c), lkey.count(c)) for c in set(tkey)))
        score = common / max(len(tkey), len(lkey))
        if score > best_score:
            best_i, best_score = i, score
    if best_i is not None and best_score >= 0.5:
        return best_i, lines[best_i][1]
    return None, None


def train_font_from_images(
    image_paths, labels, *, rotate_k: int = 0, dot_kernel: int = 0,
    pad: int = 8, max_per_char: int = 10,
) -> tuple[dict, dict]:
    """Train a glyph font from real images.

    image_paths: iterable of file paths.
    labels:      the known line strings to train (e.g. ["B.No.TEST12345", ...]).
    rotate_k:    np.rot90 k applied to each image first (sideways print -> -1).
    Returns (glyphs, stats) where glyphs = {char: [b64 template, ...]}.
    """
    from ..camera.file_source import load_image

    font: dict = {}
    stats = {"images": 0, "lines_trained": 0, "by_label": {}}
    for path in image_paths:
        try:
            image = load_image(path)
        except Exception:
            continue
        if rotate_k:
            image = np.rot90(image, k=rotate_k)
        lines = _ocr_lines(image)
        if not lines:
            continue
        stats["images"] += 1
        used: set = set()
        for label in labels:
            idx, box = _best_line(label, lines, used)
            if box is None:
                continue
            used.add(idx)
            y0, y1, x0, x1 = box
            crop = image[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
            try:
                font = register_font(crop, label, font=font, invert=None, dot_kernel=dot_kernel)
                stats["lines_trained"] += 1
                stats["by_label"][label] = stats["by_label"].get(label, 0) + 1
            except Exception:
                continue
    # cap samples per character (keep the font compact; later samples are extra)
    for ch in list(font.keys()):
        if len(font[ch]) > max_per_char:
            font[ch] = font[ch][:max_per_char]
    stats["chars"] = len(font)
    stats["glyphs"] = sum(len(v) for v in font.values())
    return font, stats
