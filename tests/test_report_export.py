import pytest

pytest.importorskip("qrcode")

from vis.cli import build_code_demo_recipe
from vis.common.events import EventBus
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.store import RecipeRepository, ResultStore
from vis.db.users import UserService
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool
from vis.engine.sim import SimulatedCodeCamera
from vis.reporting.batch_report import write_batch_report


def test_write_batch_report_produces_signed_files(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))

    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=qa_id)
    repo.approve(rid, qa_id, "Secret123", "released")

    batches = BatchService(sf)
    bid = batches.start(rid, "B-REP-01", user_id=qa_id, mfg_date="2406", exp_date="2606")

    bus = EventBus()
    bus.subscribe("inspection.result", ResultStore(sf, batch_id=bid).on_result)
    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool(), bus)
    for frame in SimulatedCodeCamera("cam1", recipe, num_frames=3, defect_rate=0.4).frames():
        pipeline.process_frame(frame)

    batches.close(bid, qa_id, "Secret123", "Batch released by QA")

    html_path, csv_path = write_batch_report(sf, bid, str(tmp_path / "reports"))

    html = open(html_path, encoding="utf-8").read()
    csv_text = open(csv_path, encoding="utf-8").read()
    assert "B-REP-01" in html
    assert "Released by user#" in html  # the release signature appears
    assert "frame_id" in csv_text and "PASS" in csv_text
