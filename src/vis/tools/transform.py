from __future__ import annotations

import numpy as np


def rotate_image(image, degrees) -> np.ndarray:
    """Rotate an image by a multiple of 90° (so sideways print reads upright)."""
    k = (int(degrees or 0) // 90) % 4
    return np.rot90(image, k) if k else np.asarray(image)


def locate_text_band(image, pad: int = 6, prefer=None) -> np.ndarray:
    """Find the text line inside a SEARCH window and return a crop of it (the
    two-region model: an outer search region tolerates print drift; the read
    happens on the located band).

    `prefer` is the taught INNER box (x, y, w, h) within the window: the band
    with the most row-overlap with it wins (stable as the window grows), falling
    back to the band nearest the inner-box centre, then to the inner crop itself
    — so changing the search margin does not change which line is read.

    Engine-free: foreground = minority class (Otsu); bands are contiguous runs
    of active rows. Full width (only neighbouring LINES corrupt a read)."""
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

    def _inner_crop():
        if prefer is None:
            return arr
        px, py, pw, ph = (int(v) for v in prefer)
        py0 = max(0, py)
        py1 = min(arr.shape[0], py + max(1, ph))
        return arr[py0:py1] if py1 > py0 else arr

    rows = (binary > 0).sum(axis=1).astype(np.float32)
    if rows.max() <= 0:
        return _inner_crop()
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
        return _inner_crop()

    if prefer is not None:
        py = int(prefer[1])
        py1 = py + max(1, int(prefer[3]))

        def overlap(band):
            return max(0, min(band[1], py1) - max(band[0], py))

        best = max(bands, key=overlap)
        if overlap(best) > 0:
            y0, y1 = best
        else:
            # Nothing overlaps the taught box: the taught line is too faint to
            # register as a band (e.g. B.No on a security mesh) while a
            # neighbouring line is dark and dense (MFG/EXP). Read exactly what the
            # operator boxed rather than snapping to a different, higher-contrast
            # line nearby — respect the drawn position over a misleading band.
            return _inner_crop()
    else:
        centre = arr.shape[0] / 2
        y0, y1 = min(bands, key=lambda b: abs((b[0] + b[1]) / 2 - centre))
    y0 = max(0, y0 - pad)
    y1 = min(arr.shape[0], y1 + pad)
    # If band detection merged several lines into one tall band — a busy/textured
    # or security-mesh background defeats Otsu, so every row reads as "active" —
    # the read would grab a neighbouring line (e.g. EXP when B.No was taught).
    # When the band is much taller than the taught box, clamp to the taught box's
    # own rows so the read stays on the line the operator actually drew.
    if prefer is not None:
        ph = max(1, int(prefer[3]))
        if (y1 - y0) > 1.8 * ph:
            py = int(prefer[1])
            y0 = max(0, py - pad)
            y1 = min(arr.shape[0], py + ph + pad)
    # full width: only the LINE needs isolating (neighbouring lines above/below
    # are what corrupt the read); horizontal drift is handled by recognition
    return arr[y0:y1]


def print_quality(image) -> dict:
    """Teach-time quality check against the documented classical-OCV floors
    (characters at least ~20 px tall, at least ~30 grey levels of contrast).
    Returns {"char_height_px", "contrast_levels", "warnings": [...]}."""
    arr = np.asarray(image)
    band = locate_text_band(arr, pad=0)
    height = int(band.shape[0])
    band_gray = band[..., :3].mean(axis=2) if band.ndim == 3 else band.astype(np.float32)
    low, high = float(np.percentile(band_gray, 2)), float(np.percentile(band_gray, 98))
    contrast = int(high - low)
    warnings = []
    if 0 < height < 20:
        warnings.append(
            f"characters ≈{height}px tall — below the ~20px floor; increase "
            "magnification or camera resolution"
        )
    if contrast < 30:
        warnings.append(
            f"only ≈{contrast} grey levels of contrast — improve lighting/strobe"
        )
    return {"char_height_px": height, "contrast_levels": contrast, "warnings": warnings}
