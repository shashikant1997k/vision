"""Pharmacode (Laetus one-track) decoding — the pharma packaging line-check code.

Pharmacode is printed on cartons and leaflets specifically so a packaging line
can confirm *the right printed component is in the machine* before a run. It is
not a general barcode: no checksum, no character set, just a number from 3 to
131070 encoded as a run of thin and thick bars — deliberately robust to poor
print and readable at speed. zxing-cpp does not decode it, which is why this
exists.

Encoding (per the published scheme), for a value N::

    while N > 0:
        if N is even:  emit THICK; N = N / 2 - 1
        else:          emit THIN;  N = (N - 1) / 2
    reverse the emitted bars

so decoding is the inverse, left to right::

    value = 0
    for bar in bars:  value = value * 2 + (2 if thick else 1)

We find the bars by binarising the crop, projecting ink down the columns, and
splitting the runs into two width classes. Bar widths are bimodal by design, so
the split point is chosen between the two clusters rather than by a fixed
threshold — that is what makes it tolerant of scale, zoom and print gain.

    from vis.tools.pharmacode import decode_pharmacode
    result = decode_pharmacode(roi_image)      # Decoded(ok, text, symbology)
"""

from __future__ import annotations

import numpy as np

from .decode import Decoded

MIN_VALUE = 3
MAX_VALUE = 131070
MIN_BARS = 2
MAX_BARS = 16          # 131070 needs 16 bars; more means we segmented noise


def _ink_columns(image) -> np.ndarray:
    """Binary column profile: True where the column contains bar ink."""
    import cv2

    arr = np.asarray(image)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gray = arr.astype(np.uint8)
    # Otsu handles the wide exposure range of carton print; bars are dark on
    # light stock, so ink is below the threshold.
    _thr, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if binary.mean() > 127:  # inverted print (light bars on dark) — flip back
        binary = 255 - binary
    coverage = binary.mean(axis=0) / 255.0
    # a column is "bar" when ink covers a decent part of the crop height; this
    # rejects speckle and the odd stray mark above/below the bars
    return coverage >= 0.5


def _runs(mask: np.ndarray) -> list[tuple[bool, int, int]]:
    """[(is_ink, start, length)] over a boolean column mask."""
    out: list[tuple[bool, int, int]] = []
    if mask.size == 0:
        return out
    start, current = 0, bool(mask[0])
    for i in range(1, mask.size):
        if bool(mask[i]) != current:
            out.append((current, start, i - start))
            start, current = i, bool(mask[i])
    out.append((current, start, int(mask.size) - start))
    return out


def _split_widths(widths: list[int]) -> float | None:
    """Threshold separating thin from thick bars.

    Bar widths are bimodal (that is the whole encoding), so we take the widest
    gap between consecutive sorted widths as the class boundary. Returns None
    when the widths do not separate — better to decline than to guess.
    """
    if not widths:
        return None
    ordered = sorted(widths)
    if ordered[-1] < 1.5 * ordered[0]:
        return None  # all one class: cannot tell thin from thick
    gaps = [(ordered[i + 1] - ordered[i], i) for i in range(len(ordered) - 1)]
    gap, index = max(gaps)
    if gap <= 0:
        return None
    return (ordered[index] + ordered[index + 1]) / 2.0


def decode_bars(thick_flags: list[bool]) -> int | None:
    """Value for a left-to-right sequence of bars (True = thick)."""
    if not (MIN_BARS <= len(thick_flags) <= MAX_BARS):
        return None
    value = 0
    for thick in thick_flags:
        value = value * 2 + (2 if thick else 1)
    return value if MIN_VALUE <= value <= MAX_VALUE else None


def encode_value(value: int) -> list[bool]:
    """Bars (True = thick) for a value — the inverse of :func:`decode_bars`.
    Used by the tests and by anyone generating a teach target."""
    if not (MIN_VALUE <= value <= MAX_VALUE):
        raise ValueError(f"pharmacode value {value} out of range {MIN_VALUE}–{MAX_VALUE}")
    bars: list[bool] = []
    n = value
    while n > 0:
        if n % 2 == 0:
            bars.append(True)
            n = n // 2 - 1
        else:
            bars.append(False)
            n = (n - 1) // 2
    bars.reverse()
    return bars


def decode_pharmacode(image) -> Decoded:
    """Decode a Pharmacode crop. Returns ``Decoded(ok=False)`` when the bars do
    not form a valid code — a wrong or unreadable component must never decode
    as some other number."""
    try:
        mask = _ink_columns(image)
    except Exception:
        return Decoded(ok=False)
    runs = _runs(mask)
    bars = [(start, length) for is_ink, start, length in runs if is_ink]
    if not (MIN_BARS <= len(bars) <= MAX_BARS):
        return Decoded(ok=False)
    widths = [length for _start, length in bars]
    threshold = _split_widths(widths)
    if threshold is not None:
        flags = [w > threshold for w in widths]
    else:
        # Every bar is the same class (value 3 is thin+thin, 6 is thick+thick) —
        # both legal, and the width histogram alone cannot say which. The
        # inter-bar space is the reference: the geometry is thin=1u, space=2u,
        # thick=3u, so bar/space is ~0.5 for thin and ~1.5 for thick. Anything
        # between those is out of spec and genuinely ambiguous — refuse, because
        # a confidently wrong component number is far worse than no read.
        first, last = bars[0][0], bars[-1][0] + bars[-1][1]
        spaces = [
            length for is_ink, start, length in runs
            if not is_ink and start > first and start + length < last
        ]
        if not spaces:
            return Decoded(ok=False)
        ratio = float(np.median(widths)) / max(float(np.median(spaces)), 1e-6)
        if ratio <= 0.75:
            flags = [False] * len(widths)     # all thin
        elif ratio >= 1.25:
            flags = [True] * len(widths)      # all thick
        else:
            return Decoded(ok=False)          # ambiguous geometry
    value = decode_bars(flags)
    if value is None:
        return Decoded(ok=False)
    return Decoded(ok=True, text=str(value), symbology="PHARMACODE")


def register() -> None:
    """Expose Pharmacode through the code-reader seam (``VIS_CODE_READER`` or a
    tool's ``reader="pharmacode"``)."""
    from .readers import register_code_reader

    register_code_reader("pharmacode", lambda image, config=None: decode_pharmacode(image))
