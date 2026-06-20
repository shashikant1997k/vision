"""Auto product-region cropping.

Industrial systems capture the full sensor frame but, for review and reports,
focus on the product — which sits in the centre of the field of view against a
relatively uniform conveyor/background. This finds the product's bounding box
(by where the image has structure/edges, vs the flat background) so we can store
a tight crop alongside the full frame: the full frame stays the audit record, the
crop is the clean, small image an operator actually looks at.

Detection is best-effort: if no clear content is found (blank frame, OpenCV
missing), it returns the full-frame box so callers always get a valid result.
"""

from __future__ import annotations

import numpy as np


def content_bbox(image, margin_frac: float = 0.04, min_area_frac: float = 0.02):
    """(x, y, w, h) of the main content in `image`. Falls back to the full frame."""
    arr = np.asarray(image)
    h, w = arr.shape[:2]
    full = (0, 0, int(w), int(h))
    try:
        import cv2
    except Exception:
        return full
    gray = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr
    # structure map: edges (print/product outline) thickened so a product reads
    # as one blob even when its interior is plain
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return full
    min_area = min_area_frac * w * h
    boxes = [cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) >= min_area]
    if not boxes:  # nothing big enough — take the single largest contour
        boxes = [cv2.boundingRect(max(cnts, key=cv2.contourArea))]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    mx, my = int(w * margin_frac), int(h * margin_frac)
    x0, y0 = max(0, x0 - mx), max(0, y0 - my)
    x1, y1 = min(w, x1 + mx), min(h, y1 + my)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return full
    return (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def crop_to_content(image, margin_frac: float = 0.04, min_area_frac: float = 0.02):
    """The image cropped to its product region (full frame if none detected)."""
    x, y, w, h = content_bbox(image, margin_frac, min_area_frac)
    return np.asarray(image)[y:y + h, x:x + w]
