import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("PIL")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from vis.tools import build_tool  # noqa: E402
from vis.tools.ocv_font import read_text, register_font  # noqa: E402


def _font(size):
    # a MONOSPACE font — like real coder fonts (uniform character cells)
    for p in [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Courier.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _dotmatrix(text, size=34, spacing=3):
    """Render `text` as DOT-MATRIX print (like a CIJ/TIJ coder): solid monospace
    glyphs sampled onto a dot grid, so each character is made of separate dots."""
    fnt = _font(size)
    bbox = fnt.getbbox("0")
    cell = bbox[2] - bbox[0] + 6
    cell = ((cell + spacing - 1) // spacing) * spacing  # multiple of spacing
    h = int(size * 1.6)
    w = len(text) * cell + 18
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    for i, ch in enumerate(text):
        # x start a multiple of spacing so every char's dot grid aligns the same
        draw.text((9 + i * cell, 6), ch, fill=0, font=fnt)
    arr = np.array(img)
    yy, xx = np.indices(arr.shape)
    keep = (xx % spacing == 0) & (yy % spacing == 0)
    out = np.full_like(arr, 255)
    out[(arr < 128) & keep] = 0  # keep dark only at grid points -> dots
    return np.stack([out] * 3, axis=-1).astype(np.uint8)


def test_font_ocv_reads_dot_matrix():
    # register the font from clear digit + letter samples (operator teaches once)
    font = register_font(_dotmatrix("0123456789"), "0123456789", dot_kernel=5, min_area=12)
    font = register_font(_dotmatrix("TESTABCDEF"), "TESTABCDEF", font=font, dot_kernel=5, min_area=12)

    text, score = read_text(_dotmatrix("12345"), font, n_chars=5, dot_kernel=5, min_area=12)
    assert text == "12345", f"got {text!r}"
    assert score > 0.5


def test_font_ocv_tool_verifies_expected():
    font = register_font(_dotmatrix("0123456789"), "0123456789", dot_kernel=5, min_area=12)
    tool = build_tool(
        "ocv_font", "lot",
        {"font": font, "match": "exact", "expected": "2024", "dot_kernel": 5, "min_area": 12},
    )
    good = tool.inspect(_dotmatrix("2024"))
    assert good.passed and good.measured_value == "2024"

    bad = tool.inspect(_dotmatrix("2025"))
    assert not bad.passed
