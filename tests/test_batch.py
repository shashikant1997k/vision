import pytest

from vis.cli import build_code_demo_recipe
from vis.common.events import EventBus
from vis.db.audit import AuditService
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.models import Batch
from vis.db.store import RecipeRepository, ResultStore
from vis.db.users import AuthError, UserService
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool
from vis.reporting.batch_report import (
    compute_summary,
    get_release_signature,
    to_csv,
    to_html,
)

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))
    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=eng_id)
    repo.approve(rid, user_id=qa_id, password="Secret123")
    return sf, eng_id, qa_id, rid


def test_batch_lifecycle_results_and_signed_report(tmp_path):
    sf, eng_id, qa_id, rid = _setup(tmp_path)
    batches = BatchService(sf)
    bid = batches.start(rid, "B-240607-01", user_id=eng_id, mfg_date="2406", exp_date="2606", mrp="100")

    bus = EventBus()
    bus.subscribe("inspection.result", ResultStore(sf, batch_id=bid).on_result)
    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool(), bus)
    for frame in SimulatedCodeCamera("cam1", recipe, num_frames=4, defect_rate=0.5).frames():
        pipeline.process_frame(frame)

    with sf() as s:
        summary = compute_summary(s, bid)
        assert summary["total"] == 4 * len(recipe.regions)
        assert summary["passed"] + summary["failed"] == summary["total"]
        assert "frame_id" in to_csv(s, bid)

    # close requires a valid e-signature
    with pytest.raises(AuthError):
        batches.close(bid, user_id=qa_id, password="WRONG")
    batches.close(bid, user_id=qa_id, password="Secret123", meaning="Released")

    with sf() as s:
        batch = s.get(Batch, bid)
        assert batch.status == "closed" and batch.closed_at
        sig = get_release_signature(s, bid)
        assert sig is not None and sig.meaning == "Released"
        report = to_html(compute_summary(s, bid), signature_line=f"Released by user#{sig.user_id}")
        assert "B-240607-01" in report
        ok, _ = AuditService(s).verify_chain()
        assert ok


def test_cannot_start_batch_on_unapproved_recipe(tmp_path):
    sf, eng_id, qa_id, rid = _setup(tmp_path)
    repo = RecipeRepository(sf)
    draft_id = repo.save_draft(build_code_demo_recipe(), user_id=eng_id)  # new version, unapproved
    batches = BatchService(sf)
    with pytest.raises(ValueError):
        batches.start(draft_id, "B-2", user_id=eng_id)
