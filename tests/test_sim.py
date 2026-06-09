"""End-to-end: simulated camera renders real GS1 codes, the pipeline decodes,
verifies, and grades them across multiple product regions."""

import pytest

from vis.cli import build_code_demo_recipe
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _run(defect_rate: float, num_frames: int = 4):
    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool())
    camera = SimulatedCodeCamera("cam1", recipe, num_frames=num_frames, defect_rate=defect_rate)
    return recipe, [r for f in camera.frames() for r in pipeline.process_frame(f)]


def test_sim_no_defect_all_pass_and_codes_decode():
    recipe, results = _run(defect_rate=0.0, num_frames=4)
    assert results
    assert all(r.passed for r in results)
    assert len(results) == 4 * len(recipe.regions)
    for r in results:
        codes = [tr for tr in r.tool_results if tr.detail.get("grade")]
        assert codes, "each region should have a graded code result"
        assert codes[0].measured_value is not None  # it actually decoded
        assert codes[0].detail["grade"]["overall"] in {"A", "B"}
        assert codes[0].detail["fields"]["batch"] == "LOT42"


def test_sim_all_defect_all_reject():
    _, results = _run(defect_rate=1.0, num_frames=3)
    assert results
    assert not any(r.passed for r in results)


def test_sim_handles_roi_larger_than_frame():
    """A recipe taught on a bigger image than the simulated frame must not crash
    (regression: settings preview ValueError on out-of-bounds blit)."""
    from vis.common.types import ROI
    from vis.domain.entities import Recipe, Region, ToolSpec
    from vis.engine.sim import SimulatedCodeCamera

    # tool ROI deliberately runs off the right/bottom edge of the sim frame
    region = Region("r", "P1", ROI(700, 400, 400, 400), "lane1",
                    [ToolSpec("code1", "code_verify", ROI(0, 0, 300, 300), {"gs1": True, "expected_data": "X"})])
    recipe = Recipe("r", "Demo", 1, [region])
    frames = list(SimulatedCodeCamera("cam1", recipe, num_frames=2, defect_rate=0.0).frames())
    assert len(frames) == 2 and frames[0].image.ndim == 3  # produced frames, no exception
