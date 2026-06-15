"""OEE computation + downtime classification."""

from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.models import Batch
from vis.db.oee import REASON_CODES, OEEService
from vis.db.store import RecipeRepository, ResultStore
from vis.db.users import UserService
from vis.engine.aggregator import RegionResult
from vis.tools.base import ToolResult


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    batch_id = BatchService(sf).start(rid, "B-001", qa)
    return sf, qa, batch_id


def _feed(sf, batch_id, good, bad):
    store = ResultStore(sf, batch_id=batch_id)
    fid = 0
    for _ in range(good):
        fid += 1
        store.on_result(RegionResult(fid, "c", "r", "l", True, [ToolResult("c", True, "x", None, 1.0)]))
    for _ in range(bad):
        fid += 1
        store.on_result(RegionResult(fid, "c", "r", "l", False, [ToolResult("c", False, "x", None, 0.0)]))


def _set_times(sf, batch_id, start_iso, end_iso):
    with sf() as s:
        b = s.get(Batch, batch_id)
        b.started_at, b.closed_at = start_iso, end_iso
        s.commit()


def test_reason_codes_have_components():
    assert REASON_CODES["VISION_MICROSTOP"][1] == "performance"
    assert REASON_CODES["BREAKDOWN_CAMERA"][1] == "availability"


def test_quality_factor(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, good=90, bad=10)
    oee = OEEService(sf).compute(batch_id)
    assert oee["quality"] == 0.9
    assert oee["total"] == 100 and oee["good"] == 90


def test_full_oee_math(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, good=540, bad=60)  # 600 units, quality 0.9
    svc = OEEService(sf)
    svc.set_target_rate(batch_id, 60)  # 60 units/min -> ideal cycle 1 s
    # 1 hour planned, 600 s downtime -> run 3000 s; availability 3000/3600
    _set_times(sf, batch_id, "2026-06-15T08:00:00+00:00", "2026-06-15T09:00:00+00:00")
    svc.log_downtime(batch_id, "CHANGEOVER", duration_s=600)
    oee = svc.compute(batch_id)
    assert abs(oee["availability"] - 3000 / 3600) < 0.01
    # performance = ideal(1s) * 600 / run(3000) = 0.2
    assert abs(oee["performance"] - 0.2) < 0.01
    assert oee["quality"] == 0.9
    assert abs(oee["oee"] - (3000 / 3600) * 0.2 * 0.9) < 0.01
    assert oee["downtime_by_reason"]["CHANGEOVER"]["seconds"] == 600


def test_open_close_downtime_classifies(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    svc = OEEService(sf)
    eid = svc.open_downtime(batch_id, station="cam1")
    duration = svc.close_downtime(eid, reason_code="BLISTER_JAM", operator_id=qa)
    assert duration >= 0
    oee = svc.compute(batch_id)
    assert "BLISTER_JAM" in oee["downtime_by_reason"]
    assert oee["downtime_by_reason"]["BLISTER_JAM"]["component"] == "performance"


def test_performance_capped_at_one(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, good=10000, bad=0)
    svc = OEEService(sf)
    svc.set_target_rate(batch_id, 1)  # absurdly low target -> would exceed 1
    _set_times(sf, batch_id, "2026-06-15T08:00:00+00:00", "2026-06-15T08:00:10+00:00")
    assert svc.compute(batch_id)["performance"] <= 1.0


def test_report_includes_oee(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, good=95, bad=5)
    OEEService(sf).set_target_rate(batch_id, 60)
    OEEService(sf).log_downtime(batch_id, "VISION_MICROSTOP", duration_s=30)
    from vis.reporting.batch_report import compute_summary, to_html

    with sf() as s:
        summary = compute_summary(s, batch_id)
    assert "oee" in summary
    html = to_html(summary)
    assert "OEE" in html and "Downtime by reason" in html and "VISION_MICROSTOP" in html
