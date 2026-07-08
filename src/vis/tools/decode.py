"""1D/2D code decoding via zxing-cpp (DataMatrix, QR, Code128, GS1, ...).

Industrial-grade robustness: a plain decode is tried first (fast path — covers a
well-lit, well-sized code in one pass; zxing itself already tries rotation,
downscale and inversion). Only when that fails does a conditioning LADDER run,
mirroring what commercial readers (DataMan/SR-class) do internally:

  1. upscale + sharpen        — small codes (< ~2 px/module) on wide-FOV lines
  2. CLAHE contrast           — faint print on foil / low-contrast substrates
  3. glare clip + stretch     — specular highlights washing out modules
  4. global-histogram binarize— uneven illumination defeating local threshold
  5. morphological close      — dotted / inkjet DPM codes (connect the dots)

The dependency is imported lazily so the package imports fine without it; the
decode call raises a clear error if it isn't installed (pip install '.[codes]').
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decoded:
    ok: bool
    text: str = ""
    symbology: str = ""


def _to_decoded(results) -> Decoded:
    res = results[0]
    symbology = getattr(res.format, "name", str(res.format))
    # Use the raw byte stream, not res.text: zxing-cpp renders control chars
    # (e.g. the GS1 group separator 0x1d) as literal tokens like "<GS>" in .text,
    # which breaks GS1 parsing. The bytes preserve 0x1d. latin-1 maps bytes 1:1
    # to code points; pharma code content is ASCII + separators, so this is exact.
    raw = getattr(res, "bytes", None)
    text = bytes(raw).decode("latin-1") if raw else res.text
    return Decoded(ok=True, text=text, symbology=symbology)


def _gray(image):
    import cv2
    import numpy as np

    arr = np.asarray(image)
    if arr.ndim == 3:
        return cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2GRAY)
    return arr


def _variants(image):
    """Conditioning ladder for hard codes — yielded lazily so the cost is paid
    only on frames where the plain decode failed."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return
    gray = _gray(image)
    h, w = gray.shape[:2]

    # 1. upscale + unsharp — small/soft codes (the dominant real-line failure)
    if max(h, w) < 800:
        scale = max(2, int(round(800 / max(1, max(h, w)))))
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        blur = cv2.GaussianBlur(up, (0, 0), 1.2)
        yield cv2.addWeighted(up, 1.6, blur, -0.6, 0)

    # 2. contrast-normalised — faint print / foil
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    yield clahe.apply(gray)

    # 3. glare-clipped — pull specular highlights to the 95th percentile
    cap = max(1, int(np.percentile(gray, 95)))
    clipped = np.clip(gray, 0, cap)
    yield cv2.normalize(clipped, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # 4. Otsu global binarize — uneven illumination defeating the local binarizer
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu

    # 5. dot-connect — dotted/inkjet DPM: close small gaps between dots
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    yield cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k)


def decode_first(image) -> Decoded:
    """Decode the first barcode found in an image (numpy array). Plain fast path
    first; the conditioning ladder only on failure. Returns Decoded(ok=False)
    if nothing decodes."""
    try:
        import zxingcpp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "zxing-cpp is not installed. Install it with: pip install '.[codes]'"
        ) from exc

    results = zxingcpp.read_barcodes(image)
    if results:
        return _to_decoded(results)
    for variant in _variants(image):
        results = zxingcpp.read_barcodes(variant)
        if results:
            return _to_decoded(results)
    return Decoded(ok=False)
