from vis.engine.aggregator import RegionResult
from vis.runtime import FailedImageLog, LiveStats
from vis.tools.base import ToolResult


def _region(passed, camera="cam1", lane="lane1", tools=()):
    return RegionResult(
        frame_id=0, camera_id=camera, region_id="r1", reject_output=lane,
        passed=passed, tool_results=list(tools),
    )


def test_stats_yield_and_reject_reasons():
    stats = LiveStats()
    stats.record(_region(True))
    stats.record(_region(False, tools=[ToolResult("code1", True), ToolResult("bno", False)]))
    stats.record(_region(False, tools=[ToolResult("bno", False)]))
    totals = stats.totals()
    assert totals["total"] == 3 and totals["passed"] == 1 and totals["failed"] == 2
    assert round(totals["yield"], 1) == 33.3
    reasons = stats.reject_reasons()
    assert reasons["bno"] == 2  # the field that failed most
    assert "code1" not in reasons  # code1 passed -> not a reject reason


def test_failed_image_log_ring_buffer():
    import numpy as np

    from vis.engine.frame import Frame

    log = FailedImageLog(capacity=3)
    for i in range(5):
        log.add(Frame("cam1", i, np.zeros((4, 4, 3), np.uint8), 0.0), [_region(False)])
    assert len(log) == 3  # only the last 3 kept
    items = log.items()
    assert [it["frame_id"] for it in items] == [2, 3, 4]
    assert log.latest()["frame_id"] == 4


def test_runner_populates_failed_log():
    import numpy as np

    from vis.cli import build_code_demo_recipe
    from vis.engine.pool import SyncPool
    from vis.engine.sim import SimulatedCodeCamera
    from vis.runtime import InspectionRunner

    log = FailedImageLog()
    stats = LiveStats()
    cam = SimulatedCodeCamera("cam1", build_code_demo_recipe(), num_frames=8, defect_rate=1.0, seed=2)
    runner = InspectionRunner([(cam, build_code_demo_recipe())], SyncPool(), stats=stats, failed_log=log)
    runner.run()
    assert len(log) > 0  # defective frames were captured for review
    assert stats.totals()["failed"] > 0
    _ = np  # imported for clarity
