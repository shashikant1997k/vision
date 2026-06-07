import numpy as np
import pytest

from vis.cli import build_code_demo_recipe
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool
from vis.runtime.overlay import draw_overlay

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def test_overlay_returns_annotated_image():
    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool())
    frame = next(SimulatedCodeCamera("cam1", recipe, num_frames=1, defect_rate=0.0).frames())
    results = pipeline.process_frame(frame)

    annotated = draw_overlay(frame.image, recipe, results)
    assert annotated.shape == frame.image.shape
    assert annotated.dtype == np.uint8
    # something was drawn
    assert not np.array_equal(annotated, frame.image)
    # a green pixel exists somewhere (a pass box was drawn)
    green = (annotated[:, :, 0] < 80) & (annotated[:, :, 1] > 120) & (annotated[:, :, 2] < 80)
    assert green.any()


def test_overlay_marks_reject_in_red():
    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool())
    frame = next(SimulatedCodeCamera("cam1", recipe, num_frames=1, defect_rate=1.0).frames())
    results = pipeline.process_frame(frame)

    annotated = draw_overlay(frame.image, recipe, results)
    red = (annotated[:, :, 0] > 150) & (annotated[:, :, 1] < 90) & (annotated[:, :, 2] < 90)
    assert red.any()
