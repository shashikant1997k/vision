"""Print Inspect tool — reject on print QUALITY, not just on wrong text.

A drifting coder still prints readable characters long before it prints illegible
ones. This tool is what catches it while it is still maintenance rather than a
batch deviation.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vis.tools.print_inspect import teach_reference
from vis.tools.registry import build_tool, registered_types


def text_img(text="B.No.TEST12345", thickness=2, blur=0, fade=0, dropout=0.0, seed=0):
    img = np.full((60, 460), 255, np.uint8)
    cv2.putText(img, text, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, thickness, cv2.LINE_AA)
    if dropout:
        rng = np.random.RandomState(seed)
        img[(rng.rand(*img.shape) < dropout) & (img < 128)] = 255
    if fade:
        img = np.clip(img.astype(int) + fade, 0, 255).astype(np.uint8)
    if blur:
        img = cv2.GaussianBlur(img, (blur | 1, blur | 1), 0)
    return img


@pytest.fixture
def tool():
    return build_tool("print_inspect", "pi1", {"min_grade": "C"})


def test_tool_is_registered():
    assert "print_inspect" in registered_types()


def test_good_print_passes(tool):
    assert tool.inspect(text_img()).passed


@pytest.mark.parametrize(
    "name,image",
    [
        ("faded", text_img(thickness=1, fade=90)),
        ("smeared", text_img(thickness=5, blur=7)),
        ("dropout", text_img(dropout=0.45, seed=3)),
        ("blank", np.full((60, 460), 255, np.uint8)),
    ],
)
def test_degraded_print_is_rejected(tool, name, image):
    assert not tool.inspect(image).passed, f"{name} print should reject"


def test_result_reports_the_grade_and_character_count(tool):
    result = tool.inspect(text_img())
    assert result.detail["grade"] in "ABCDF"
    assert result.detail["n_chars"] > 0
    assert result.expected_value == "≥ C"
    assert "grade" in result.measured_value


def test_worst_characters_are_reported(tool):
    """A maintenance engineer needs 'which characters', not just a letter."""
    result = tool.inspect(text_img(dropout=0.45, seed=3))
    worst = result.detail["worst_characters"]
    assert worst and all({"index", "grade", "stroke_width_px"} <= set(c) for c in worst)


def test_min_grade_is_configurable():
    lenient = build_tool("print_inspect", "a", {"min_grade": "F"})
    strict = build_tool("print_inspect", "b", {"min_grade": "A"})
    image = text_img(dropout=0.3, seed=5)
    assert lenient.inspect(image).passed
    assert not strict.inspect(image).passed


def test_invalid_min_grade_falls_back_to_c():
    tool = build_tool("print_inspect", "c", {"min_grade": "Z"})
    assert tool.inspect(text_img()).expected_value == "≥ C"


def test_min_chars_catches_mostly_missing_print():
    tool = build_tool("print_inspect", "d", {"min_grade": "F", "min_chars": 10})
    result = tool.inspect(text_img("AB"))
    assert not result.passed and "character" in result.measured_value


def test_confidence_tracks_the_grade(tool):
    good = tool.inspect(text_img()).confidence
    bad = tool.inspect(text_img(thickness=1, fade=90)).confidence
    assert good > bad


def test_teach_reference_captures_the_golden_stroke_width():
    reference = teach_reference(text_img())
    assert reference["median_stroke_px"] > 0


def test_reference_catches_uniform_fade():
    """Uniform fade shifts every character, so the line's own median cannot see
    it — the taught reference is what catches slow drift."""
    reference = teach_reference(text_img())
    tool = build_tool("print_inspect", "e", {"min_grade": "B", "reference": reference})
    assert not tool.inspect(text_img(thickness=1, fade=90)).passed


def test_grading_failure_does_not_raise(tool, monkeypatch):
    monkeypatch.setattr(
        "vis.tools.print_inspect.grade_line",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = tool.inspect(text_img())
    assert not result.passed and "failed" in result.measured_value
