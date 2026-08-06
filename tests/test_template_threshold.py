"""Template-match thresholds: a safe default, and teaching one from real samples.

Normalised cross-correlation cannot reliably tell similar TEXT apart — that is
what the OCV/OCR tools are for. These tests pin the safety behaviour: the
untaught default must not sit below what wrong artwork can score, and teaching
must say plainly when a threshold cannot be trusted.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vis.tools.general import (
    DEFAULT_TEMPLATE_MIN_SCORE,
    register_template,
    suggest_min_score,
)
from vis.tools.registry import build_tool


def art(text="LOT 4221", noise=0, shift=0):
    img = np.full((80, 240), 255, np.uint8)
    cv2.putText(img, text, (12 + shift, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2, cv2.LINE_AA)
    if noise:
        rng = np.random.RandomState(noise)
        img = np.clip(img.astype(int) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return img


@pytest.fixture
def template():
    return register_template(art())


# ---- the default ---------------------------------------------------------
def test_default_is_above_what_wrong_text_can_score(template):
    """The old 0.6 default sat below the ~0.7 similar-text can reach."""
    assert DEFAULT_TEMPLATE_MIN_SCORE > 0.7


def test_default_rejects_similar_wrong_text(template):
    tool = build_tool("template_match", "t", {"template": template})
    assert not tool.inspect(art("LOT 9999")).passed


def test_good_part_still_passes_on_the_default(template):
    tool = build_tool("template_match", "t", {"template": template})
    assert tool.inspect(art()).passed


def test_explicit_threshold_is_always_honoured(template):
    """A validated recipe that stored its threshold must be unaffected."""
    tool = build_tool("template_match", "t", {"template": template, "min_score": 0.1})
    assert tool.inspect(art("LOT 9999")).passed
    assert tool.inspect(art("LOT 9999")).expected_value == "≥ 0.10"


def test_untaught_threshold_warns_once(template, caplog):
    tool = build_tool("template_match", "t", {"template": template})
    with caplog.at_level("WARNING"):
        tool.inspect(art())
        tool.inspect(art())
    assert sum("no taught min_score" in r.message for r in caplog.records) == 1


def test_taught_threshold_does_not_warn(template, caplog):
    tool = build_tool("template_match", "t", {"template": template, "min_score": 0.9})
    with caplog.at_level("WARNING"):
        tool.inspect(art())
    assert not any("no taught min_score" in r.message for r in caplog.records)


# ---- teaching a threshold ------------------------------------------------
def test_needs_at_least_one_good_sample(template):
    with pytest.raises(ValueError):
        suggest_min_score(template, [])


def test_separated_populations_give_a_threshold_between_them(template):
    good = [art(), art(noise=6)]
    bad = [art("XX 0000")]
    result = suggest_min_score(template, good, bad)
    assert result["separated"] is True and result["warning"] is None
    assert result["bad"]["max"] < result["min_score"] < result["good"]["min"]


def test_overlapping_populations_are_reported_as_unusable(template):
    """Realistic variation makes good and bad text scores overlap — no threshold
    can separate them, and the operator must be told that."""
    good = [art(noise=n, shift=s) for n in (0, 8, 14) for s in (0, 2)]
    bad = [art("XX 0000"), art("LOT 9999")]
    result = suggest_min_score(template, good, bad)
    if result["separated"] is False:
        assert "OVERLAP" in result["warning"] and "OCV" in result["warning"]


def test_no_bad_samples_is_reported_as_unproven(template):
    """Fitting the good parts proves nothing about rejecting a wrong one."""
    result = suggest_min_score(template, [art(), art(noise=6)])
    assert result["separated"] is None
    assert "no bad samples" in result["warning"]
    assert result["bad"]["n"] == 0


def test_suggestion_stays_in_range(template):
    result = suggest_min_score(template, [art(noise=40)])
    assert 0.0 <= result["min_score"] <= 1.0


def test_tool_config_is_passed_through_to_scoring(template):
    """The threshold must be taught with the settings the tool will run with."""
    skewed = [art(), art(noise=6)]
    without = suggest_min_score(template, skewed)
    with_rotation = suggest_min_score(template, skewed, angle_range=10)
    assert with_rotation["good"]["min"] >= without["good"]["min"]
