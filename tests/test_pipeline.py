from vis.cli import build_demo_recipe
from vis.engine.camera import FakeCamera
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool


def _run(defect_rate: float, num_frames: int):
    recipe = build_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool())
    camera = FakeCamera("cam1", recipe, num_frames=num_frames, defect_rate=defect_rate)
    return recipe, [r for f in camera.frames() for r in pipeline.process_frame(f)]


def test_pipeline_no_defects_all_pass():
    recipe, results = _run(defect_rate=0.0, num_frames=5)
    assert results
    assert all(r.passed for r in results)
    # one result per region per frame (multi-product in one FOV)
    assert len(results) == 5 * len(recipe.regions)


def test_pipeline_all_defects_all_reject():
    _, results = _run(defect_rate=1.0, num_frames=3)
    assert results
    assert not any(r.passed for r in results)
    assert all(r.reject_output.startswith("lane") for r in results)
