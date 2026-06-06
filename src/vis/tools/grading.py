"""Approximate, inline code-quality grading.

IMPORTANT: this is a *process-control* indicator, NOT a certified ISO/IEC
15415/15416 verifier grade. A certified grade legally requires conformant
verifier hardware (ISO/IEC 15426); software/an inline camera can only
approximate it (decision D-012). We compute a couple of robust, image-derived
parameters (decode success, symbol contrast) and map them to A–F bands, taking
the overall as the lowest — mirroring the ISO grading structure without
claiming conformance.
"""

from __future__ import annotations

import numpy as np

_LETTER = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}


def _to_gray(image) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float32)
    if arr.ndim == 3:
        return arr[..., :3].mean(axis=2)
    return arr


def symbol_contrast(gray: np.ndarray) -> float:
    """SC ≈ (max - min reflectance) normalised to 0..1."""
    if gray.size == 0:
        return 0.0
    return float(gray.max() - gray.min()) / 255.0


def _sc_grade(sc: float) -> int:
    if sc >= 0.70:
        return 4
    if sc >= 0.55:
        return 3
    if sc >= 0.40:
        return 2
    if sc >= 0.20:
        return 1
    return 0


def approximate_grade(image, decoded: bool) -> dict:
    gray = _to_gray(image)
    sc = symbol_contrast(gray)
    sc_grade = _sc_grade(sc)
    decode_grade = 4 if decoded else 0
    overall = min(sc_grade, decode_grade)
    return {
        "overall": _LETTER[overall],
        "overall_value": overall,
        "decode": _LETTER[decode_grade],
        "symbol_contrast": round(sc, 3),
        "symbol_contrast_grade": _LETTER[sc_grade],
        "method": "approximate process-control grade — NOT a certified ISO 15415/15416 verifier grade",
    }
