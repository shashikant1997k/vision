"""Pharmacode (Laetus one-track) — the pharma line-clearance code.

Safety stance: a wrong component number is far worse than no read, so every
ambiguous case must refuse rather than guess.
"""

from __future__ import annotations

import numpy as np
import pytest

from vis.tools.pharmacode import (
    MAX_VALUE,
    MIN_VALUE,
    decode_bars,
    decode_pharmacode,
    encode_value,
)


def render(value, *, narrow=4, wide=12, gap=8, height=60, pad=8,
           invert=False, noise=0.0):
    """Render a Pharmacode to spec geometry (thin 1u, space 2u, thick 3u)."""
    widths = [wide if thick else narrow for thick in encode_value(value)]
    width = pad * 2 + sum(widths) + gap * (len(widths) - 1)
    img = np.full((height, width), 255, np.uint8)
    x = pad
    for w in widths:
        img[6:height - 6, x:x + w] = 20
        x += w + gap
    if noise:
        rng = np.random.RandomState(value)
        img = np.clip(img.astype(int) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return 255 - img if invert else img


# ---- the encoding itself -------------------------------------------------
@pytest.mark.parametrize("value", [3, 4, 5, 6, 7, 17, 99, 255, 1234, 12345, 65535, MAX_VALUE])
def test_encode_decode_round_trip(value):
    assert decode_bars(encode_value(value)) == value


def test_round_trip_over_a_dense_range():
    assert all(decode_bars(encode_value(v)) == v for v in range(MIN_VALUE, 600))


def test_out_of_range_values_are_rejected():
    for bad in (0, 1, 2, MAX_VALUE + 1):
        with pytest.raises(ValueError):
            encode_value(bad)


def test_decode_bars_rejects_impossible_bar_counts():
    assert decode_bars([]) is None
    assert decode_bars([True]) is None            # one bar cannot reach 3
    assert decode_bars([True] * 20) is None       # beyond the code's range


# ---- decoding from an image ----------------------------------------------
@pytest.mark.parametrize("value", [3, 6, 17, 255, 1234, 12345, MAX_VALUE])
def test_decodes_a_clean_render(value):
    result = decode_pharmacode(render(value))
    assert result.ok and result.text == str(value)
    assert result.symbology == "PHARMACODE"


@pytest.mark.parametrize("value", [3, 6, 99, 4321])
@pytest.mark.parametrize(
    "kwargs",
    [
        {"narrow": 3, "wide": 9, "gap": 6},        # small print
        {"narrow": 8, "wide": 24, "gap": 16},      # large / zoomed
        {"noise": 25},                             # noisy carton
        {"invert": True},                          # light bars on dark stock
    ],
)
def test_decodes_across_print_conditions(value, kwargs):
    assert decode_pharmacode(render(value, **kwargs)).text == str(value)


def test_all_thin_and_all_thick_codes_both_decode():
    """The hard case: with one bar class the width histogram cannot decide, so
    the inter-bar space resolves it (thin < space < thick)."""
    assert decode_pharmacode(render(3)).text == "3"    # thin, thin
    assert decode_pharmacode(render(6)).text == "6"    # thick, thick


# ---- safety: never invent a number ---------------------------------------
def test_blank_image_is_refused():
    assert not decode_pharmacode(np.full((40, 80), 255, np.uint8)).ok


def test_solid_black_is_refused():
    assert not decode_pharmacode(np.zeros((40, 80), np.uint8)).ok


def test_random_noise_is_refused():
    noise = np.random.RandomState(1).randint(0, 255, (40, 80)).astype(np.uint8)
    assert not decode_pharmacode(noise).ok


def test_out_of_spec_geometry_never_produces_a_wrong_number():
    """Gaps wider than the thick bars break the thin<space<thick ordering. That
    is ambiguous, and a confidently wrong component number would be dangerous."""
    for value in (3, 6, 65535, MAX_VALUE):
        result = decode_pharmacode(render(value, gap=14))
        assert (not result.ok) or result.text == str(value)


def test_single_bar_is_refused():
    img = np.full((40, 40), 255, np.uint8)
    img[6:34, 10:16] = 20
    assert not decode_pharmacode(img).ok


def test_colour_input_is_handled():
    gray = render(1234)
    rgb = np.stack([gray] * 3, axis=-1)
    assert decode_pharmacode(rgb).text == "1234"


# ---- reader seam ---------------------------------------------------------
def test_registered_as_a_code_reader():
    from vis.tools.readers import available_code_readers, get_code_reader

    assert "pharmacode" in available_code_readers()
    assert get_code_reader("pharmacode")(render(4321), None).text == "4321"
