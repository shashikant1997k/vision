from __future__ import annotations

import numpy as np


def rotate_image(image, degrees) -> np.ndarray:
    """Rotate an image by a multiple of 90° (so sideways print reads upright)."""
    k = (int(degrees or 0) // 90) % 4
    return np.rot90(image, k) if k else np.asarray(image)


def locate_text_band(image, pad: int = 6) -> np.ndarray:
    """Find the text line nearest the centre of a SEARCH window and return a
    tight crop of it (the two-region model: an outer search region tolerates
    print drift; the read happens on the located inner band).

    Engine-free: foreground = minority class (Otsu), pick the horizontal band of
    foreground rows whose centre is closest to the window centre, then trim the
    column extent. Falls back to the full window when nothing is found."""
    arr = np.asarray(image)
    gray = arr[..., :3].mean(axis=2) if arr.ndim == 3 else arr.astype(np.float32)
    try:
        import cv2

        _, binary = cv2.threshold(
            gray.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        if (binary == 255).mean() > 0.5:
            binary = 255 - binary
    except Exception:
        threshold = gray.mean()
        binary = ((gray < threshold) * 255).astype(np.uint8)
        if (binary == 255).mean() > 0.5:
            binary = 255 - binary

    rows = (binary > 0).sum(axis=1).astype(np.float32)
    if rows.max() <= 0:
        return arr
    active = rows > 0.15 * rows.max()
    # contiguous active bands
    bands = []
    start = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(active)))
    if not bands:
        return arr
    centre = arr.shape[0] / 2
    y0, y1 = min(bands, key=lambda b: abs((b[0] + b[1]) / 2 - centre))
    y0 = max(0, y0 - pad)
    y1 = min(arr.shape[0], y1 + pad)
    # full width: only the LINE needs isolating (neighbouring lines above/below
    # are what corrupt the read); horizontal drift is handled by recognition
    return arr[y0:y1]
