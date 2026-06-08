from vis.engine.aggregator import RegionResult
from vis.integrations.plc import RecordingPlcLink
from vis.io import EncoderRejectConfig, EncoderRejectController, SimulatedIO


def _reject(lane="lane1", camera="cam1"):
    return RegionResult(0, camera, "r1", lane, False, [])


def test_encoder_reject_fires_at_distance_not_before():
    io = SimulatedIO()
    ctrl = EncoderRejectController(
        [EncoderRejectConfig("lane1", channel=1, eject_distance_pulses=10)], io=io
    )
    ctrl.reject(_reject())  # queued at position 0 -> fire at 10
    ctrl.tick(5)
    assert io.pulse_count(1) == 0 and ctrl.pending == 1  # not yet at the ejector
    ctrl.tick(5)  # now at position 10
    assert io.pulse_count(1) == 1 and ctrl.pending == 0  # ejected exactly on arrival


def test_encoder_reject_is_speed_independent_with_queue():
    io = SimulatedIO()
    ctrl = EncoderRejectController(
        [EncoderRejectConfig("lane1", channel=1, eject_distance_pulses=8)], io=io
    )
    ctrl.reject(_reject())  # fire at 8
    ctrl.tick(3)  # pos 3
    ctrl.reject(_reject())  # fire at 11
    ctrl.tick(5)  # pos 8 -> first fires
    assert io.pulse_count(1) == 1
    ctrl.tick(3)  # pos 11 -> second fires
    assert io.pulse_count(1) == 2
    assert ctrl.fired == 2


def test_encoder_reject_unmatched_lane():
    ctrl = EncoderRejectController([EncoderRejectConfig("laneX", 1, 5)])
    ctrl.reject(_reject(lane="nope"))
    assert ctrl.unmatched == 1 and ctrl.pending == 0


def test_plc_link_records_results_and_counters():
    plc = RecordingPlcLink()
    plc.on_result(RegionResult(0, "cam1", "r1", "lane1", True, []))
    plc.on_result(RegionResult(0, "cam1", "r2", "lane2", False, []))
    plc.write_counters({"total": 2, "passed": 1, "failed": 1})
    assert plc.results == [("r1", True, "lane1"), ("r2", False, "lane2")]
    assert plc.counters[-1]["passed"] == 1
