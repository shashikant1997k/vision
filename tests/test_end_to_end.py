"""Full-workflow integration test: teach a recipe, approve it, run a batch on the
line (simulated), close it with an electronic signature, generate the report, and
verify the audit chain — the whole product in one pass."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("qrcode")

from sqlalchemy import func, select  # noqa: E402

from vis.cli import _gs1  # noqa: E402
from vis.common.events import EventBus  # noqa: E402
from vis.common.types import ROI  # noqa: E402
from vis.db.audit import AuditService  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.batches import BatchService  # noqa: E402
from vis.db.models import Batch, InspectionResult  # noqa: E402
from vis.db.store import RecipeRepository, ResultStore  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.engine.pipeline import InspectionPipeline  # noqa: E402
from vis.engine.pool import SyncPool  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.hmi.teach_model import TeachModel, tool_config  # noqa: E402
from vis.reporting.batch_report import write_batch_report  # noqa: E402


def test_full_workflow_teach_run_close_report_audit(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/vis.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))

    # 1. TEACH a recipe and APPROVE it (two-component e-signature)
    model = TeachModel("Tablets 500mg", "tablets")
    i = model.add_region("Product 1", ROI(0, 0, 800, 480), "lane1")
    model.add_tool(
        i, "code1", "code_verify", ROI(30, 30, 300, 300), tool_config("code_verify", _gs1("SN0001"))
    )
    rid = RecipeRepository(sf).save_draft(model.to_recipe(), user_id=qa)
    RecipeRepository(sf).approve(rid, qa, "Secret123", "released")
    recipe = RecipeRepository(sf).load(rid)

    # 2. START a batch against the approved recipe
    batch_id = BatchService(sf).start(rid, "B-2026-001", qa)

    # 3. RUN the line: inspect frames, publishing results into the batch
    bus = EventBus()
    bus.subscribe("inspection.result", ResultStore(sf, batch_id=batch_id).on_result)
    pipeline = InspectionPipeline(recipe, SyncPool(), bus=bus)
    for frame in SimulatedCodeCamera("cam1", recipe, num_frames=20, defect_rate=0.2, seed=3).frames():
        pipeline.process_frame(frame)

    # 4. CLOSE (release) the batch with an electronic signature
    BatchService(sf).close(batch_id, qa, "Secret123", "released")

    # 5. REPORT
    html_path, _ = write_batch_report(sf, batch_id, str(tmp_path / "reports"))
    assert Path(html_path).exists()
    report = Path(html_path).read_text()
    assert "B-2026-001" in report

    # 6. Verify: every product recorded, batch closed, audit chain intact
    with sf() as s:
        n_results = s.execute(
            select(func.count()).select_from(InspectionResult).where(InspectionResult.batch_id == batch_id)
        ).scalar()
        batch = s.get(Batch, batch_id)
        chain_ok, _ = AuditService(s).verify_chain()
    assert n_results == 20  # one product per frame (single-region recipe)
    assert batch.status == "closed"
    assert chain_ok  # tamper-evident audit chain verifies across the whole workflow
