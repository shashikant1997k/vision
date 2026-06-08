"""Part location / fixturing.

Teach a small template patch from the master image (a distinctive feature: a
logo, an edge, a corner). At runtime the template is found in each frame and the
(dx, dy) offset from its taught position is applied to every ROI in the region —
so the inspections follow the part as it shifts on the line, instead of failing
when the product isn't in exactly the taught spot.

Translation-only (cv2.matchTemplate, normalised cross-correlation). Rotation
tolerance is a later enhancement.
"""

from __future__ import annotations

import numpy as np

from ..domain.entities import Fixture


def encode_template(image, roi) -> bytes:
    """Crop `roi` from `image` and PNG-encode it as a grayscale template."""
    import cv2

    arr = np.asarray(image)
    patch = arr[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
    if patch.ndim == 3:
        patch = cv2.cvtColor(patch[..., :3], cv2.COLOR_RGB2GRAY)
    ok, buf = cv2.imencode(".png", patch)
    return buf.tobytes()


def _decode(template: bytes):
    import cv2

    arr = np.frombuffer(template, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)


def locate(image, fixture: Fixture) -> tuple[int, int, float]:
    """Return (dx, dy, score) — the part's offset from its taught position.
    (0, 0, score) means no shift; a low score (< fixture.min_score) means the
    part wasn't found and the caller should not trust/apply the offset."""
    try:
        import cv2

        template = _decode(fixture.template)
        if template is None:
            return 0, 0, 0.0
        th, tw = template.shape[:2]
        arr = np.asarray(image)
        gray = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr
        height, width = gray.shape[:2]
        margin = fixture.search_margin
        x0 = max(0, fixture.anchor_x - margin)
        y0 = max(0, fixture.anchor_y - margin)
        x1 = min(width, fixture.anchor_x + tw + margin)
        y1 = min(height, fixture.anchor_y + th + margin)
        search = gray[y0:y1, x0:x1]
        if search.shape[0] < th or search.shape[1] < tw:
            return 0, 0, 0.0
        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        found_x = x0 + max_loc[0]
        found_y = y0 + max_loc[1]
        return found_x - fixture.anchor_x, found_y - fixture.anchor_y, float(max_val)
    except Exception:
        return 0, 0, 0.0
