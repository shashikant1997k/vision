import pytest

from vis.cli import build_code_demo_recipe
from vis.engine.pool import SyncPool
from vis.runtime import InspectionRunner, LiveStats, LiveView, RecordingRejectHandler

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def test_runtime_runs_multiple_cameras_concurrently():
    recipe = build_code_demo_recipe()
    cameras = [
        SimulatedCodeCamera(f"cam{i + 1}", recipe, num_frames=3, defect_rate=0.0, seed=i)
        for i in range(2)
    ]
    stats = LiveStats()
    live = LiveView()
    runner = InspectionRunner(
        [(c, recipe) for c in cameras], SyncPool(), stats=stats, live_view=live
    )
    runner.run()

    snapshot = stats.snapshot()
    assert set(snapshot) == {"cam1", "cam2"}
    assert stats.totals()["total"] == 2 * 3 * len(recipe.regions)
    assert stats.totals()["passed"] == stats.totals()["total"]  # no defects -> all pass
    assert live.latest("cam1") is not None
    assert live.latest("cam2") is not None


def test_runtime_routes_rejects():
    recipe = build_code_demo_recipe()
    camera = SimulatedCodeCamera("cam1", recipe, num_frames=4, defect_rate=1.0, seed=0)
    handler = RecordingRejectHandler()
    runner = InspectionRunner([(camera, recipe)], SyncPool(), reject_handler=handler)
    runner.run()

    assert handler.count() == 4 * len(recipe.regions)  # every product defective
    assert runner.stats.totals()["passed"] == 0
    # rejects carry the lane routing
    assert all(lane and lane.startswith("lane") for _, _, lane in handler.rejects)
