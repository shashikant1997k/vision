"""Built-in starter fonts + sample segmentation for the OCV font library.

Industrial print falls into known families (docs/11-ocv-fonts.md): dot-matrix
CIJ/DOD, near-solid TIJ/TTO/laser. We generate starter font models for the
common cases so OCV works out of the box; real deployments then TRAIN the
customer's actual coder font from line images (segment → annotate → save),
which simply adds more glyph templates per character.
"""

from __future__ import annotations

import base64

import numpy as np

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./-:"

# print technologies (key, label, suggested dot-connect kernel)
PRINT_TYPES = [
    ("cij", "CIJ — continuous inkjet (dot matrix)", 5),
    ("dod", "DOD — large-character inkjet (coarse dots)", 9),
    ("tij", "TIJ — thermal inkjet (300 dpi)", 2),
    ("laser", "Laser marking", 0),
    ("tto", "TTO — thermal transfer", 0),
    ("digital", "Digital / pre-printed", 0),
]


def _render_solid(ch: str, size=64):
    """Render one character solid (white on black) with a clean system font."""
    from PIL import Image, ImageDraw, ImageFont

    for path in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:\\Windows\\Fonts\\consola.ttf",
    ):
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    else:  # pragma: no cover - default bitmap font fallback
        font = ImageFont.load_default()
    img = Image.new("L", (size * 2, size * 2), 0)
    ImageDraw.Draw(img).text((size // 2, size // 4), ch, fill=255, font=font)
    return np.array(img)


def _tight(arr):
    ys, xs = np.where(arr > 64)
    if xs.size == 0:
        return None
    return arr[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _to_template(binary) -> str:
    """Normalise to the matcher's template size and PNG/base64-encode."""
    import cv2

    from .ocv_font import NORM

    glyph = cv2.resize(binary.astype(np.uint8), NORM, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", glyph)
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _solid_glyph(ch: str) -> str | None:
    tight = _tight(_render_solid(ch))
    if tight is None:
        return None
    return _to_template((tight > 64).astype(np.uint8) * 255)


def _dot_glyph(ch: str, grid=(5, 7), dot_px=6, gap_px=3) -> str | None:
    """Sample a solid glyph onto a rows×cols dot grid and draw round dots —
    what a CIJ coder does physically."""
    import cv2

    cols, rows = grid
    tight = _tight(_render_solid(ch))
    if tight is None:
        return None
    cells = cv2.resize(tight, (cols, rows), interpolation=cv2.INTER_AREA) > 64
    pitch = dot_px + gap_px
    canvas = np.zeros((rows * pitch, cols * pitch), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            if cells[r, c]:
                cy, cx = r * pitch + pitch // 2, c * pitch + pitch // 2
                cv2.circle(canvas, (cx, cy), dot_px // 2, 255, -1)
    tight_dots = _tight(canvas)
    return _to_template(tight_dots)


def builtin_fonts() -> list[dict]:
    """Generated starter font models (name, print_type, dot_kernel, glyphs)."""
    fonts = []
    specs = [
        ("Dot matrix 5×7 (CIJ)", "cij", 7, lambda ch: _dot_glyph(ch, (5, 7))),
        ("Dot matrix 9×7 (CIJ quality)", "cij", 5, lambda ch: _dot_glyph(ch, (7, 9), dot_px=5, gap_px=2)),
        ("Solid print (TIJ/TTO/laser)", "tto", 0, _solid_glyph),
    ]
    for name, print_type, kernel, make in specs:
        glyphs: dict[str, list[str]] = {}
        for ch in CHARSET:
            template = make(ch)
            if template:
                glyphs[ch] = [template]
        fonts.append({"name": name, "print_type": print_type, "dot_kernel": kernel, "glyphs": glyphs})
    return fonts


def segment_sample(image, text: str, invert=None, dot_kernel: int = 0, min_area: int = 10):
    """Segment a training sample into per-character glyphs for annotation.

    Returns [(suggested_char, template_b64), ...] in left-to-right order, one per
    non-space character of `text` (the operator corrects any wrong suggestion)."""
    from .ocv_font import _binarize, _dot_connect, _even_split, _gray, _norm_glyph

    import cv2

    chars = [c for c in text.upper() if not c.isspace()]
    gray = _gray(np.asarray(image))
    binary = _dot_connect(_binarize(gray, invert), dot_kernel)
    boxes = _even_split(binary, len(chars))
    out = []
    for ch, box in zip(chars, boxes):
        glyph = _norm_glyph(binary, box)
        ok, buf = cv2.imencode(".png", glyph)
        out.append((ch, base64.b64encode(buf.tobytes()).decode("ascii")))
    return out
