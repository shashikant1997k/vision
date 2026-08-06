"""Pattern matching with rotation tolerance and polarity handling."""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from vis.tools.registry import build_tool


def artwork(text="LOT 4221", angle=0.0, invert=False):
    img = np.full((80, 240), 255, np.uint8)
    cv2.putText(img, text, (12, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2, cv2.LINE_AA)
    if angle:
        matrix = cv2.getRotationMatrix2D((120, 40), angle, 1.0)
        img = cv2.warpAffine(img, matrix, (240, 80), borderValue=255)
    return 255 - img if invert else img


@pytest.fixture
def template_b64():
    return base64.b64encode(cv2.imencode(".png", artwork())[1].tobytes()).decode()


def tool(template_b64, **config):
    return build_tool("template_match", "t", {"template": template_b64, **config})


def test_missing_template_fails_cleanly():
    result = build_tool("template_match", "t", {}).inspect(artwork())
    assert not result.passed and "no template" in result.measured_value


def test_aligned_part_matches(template_b64):
    assert tool(template_b64).inspect(artwork()).passed


def test_default_behaviour_is_unchanged(template_b64):
    """No angle_range means no rotation search — existing recipes must not shift."""
    result = tool(template_b64).inspect(artwork())
    assert "angle" not in result.detail
    assert "°" not in result.measured_value


@pytest.mark.parametrize("angle", [-7, -4, 4, 7])
def test_rotation_search_recovers_a_skewed_good_part(template_b64, angle):
    without = tool(template_b64).inspect(artwork(angle=angle))
    with_search = tool(template_b64, angle_range=10).inspect(artwork(angle=angle))
    assert with_search.detail["score"] > without.detail["score"]
    assert with_search.passed


def test_found_angle_is_reported(template_b64):
    """A part that always matches off-angle means the fixture has drifted."""
    result = tool(template_b64, angle_range=10).inspect(artwork(angle=6))
    assert result.detail["angle"] != 0
    assert "°" in result.measured_value


def test_rotation_search_does_not_rescue_wrong_artwork(template_b64):
    """Tolerating skew must not turn into tolerating the wrong part."""
    good = tool(template_b64, angle_range=10).inspect(artwork()).detail["score"]
    wrong = tool(template_b64, angle_range=10).inspect(artwork("XX 0000")).detail["score"]
    assert wrong < good


def test_inverted_polarity_needs_the_flag(template_b64):
    inverted = artwork(invert=True)
    assert not tool(template_b64).inspect(inverted).passed
    assert tool(template_b64, allow_inverted=True).inspect(inverted).passed


def test_angle_step_is_respected(template_b64):
    """A coarse step still finds a nearby angle; it just searches fewer of them."""
    fine = tool(template_b64, angle_range=10, angle_step=1).inspect(artwork(angle=5))
    coarse = tool(template_b64, angle_range=10, angle_step=5).inspect(artwork(angle=5))
    assert fine.passed and coarse.passed


def test_zero_angle_step_falls_back_instead_of_hanging(template_b64):
    result = tool(template_b64, angle_range=4, angle_step=0).inspect(artwork(angle=2))
    assert result.detail["score"] > 0
