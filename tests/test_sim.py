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
