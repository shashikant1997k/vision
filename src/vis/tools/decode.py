"""1D/2D code decoding via zxing-cpp (DataMatrix, QR, Code128, GS1, ...).

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


def decode_first(image) -> Decoded:
    """Decode the first barcode found in an image (numpy array). Returns
    Decoded(ok=False) if nothing decodes."""
    try:
        import zxingcpp
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "zxing-cpp is not installed. Install it with: pip install '.[codes]'"
        ) from exc

    results = zxingcpp.read_barcodes(image)
    if not results:
        return Decoded(ok=False)
    res = results[0]
    symbology = getattr(res.format, "name", str(res.format))
    # Use the raw byte stream, not res.text: zxing-cpp renders control chars
    # (e.g. the GS1 group separator 0x1d) as literal tokens like "<GS>" in .text,
    # which breaks GS1 parsing. The bytes preserve 0x1d. latin-1 maps bytes 1:1
    # to code points; pharma code content is ASCII + separators, so this is exact.
    raw = getattr(res, "bytes", None)
    text = bytes(raw).decode("latin-1") if raw else res.text
    return Decoded(ok=True, text=text, symbology=symbology)
