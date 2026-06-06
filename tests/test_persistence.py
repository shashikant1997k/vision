import pytest
from sqlalchemy import func, select

from vis.cli import build_code_demo_recipe
from vis.common.events import EventBus
from vis.db.audit import AuditService
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.models import CodeReadRow, GradeResultRow, InspectionResult, Recipe
from vis.db.store import RecipeRepository, ResultStore
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool

pytest.importorskip("qrcode")
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return make_session_factory(engine)


def test_pipeline_results_persisted_with_codereads_and_grades(tmp_path):
    sf = _sf(tmp_path)
    bus = EventBus()
    bus.subscribe("inspection.result", ResultStore(sf).on_result)

    recipe = build_code_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool(), bus)
    for frame in SimulatedCodeCamera("cam1", recipe, num_frames=2, defect_rate=0.0).frames():
        pipeline.process_frame(frame)

    with sf() as s:
        n_results = s.execute(select(func.count()).select_from(InspectionResult)).scalar()
        codes = s.execute(select(CodeReadRow)).scalars().all()
        grades = s.execute(select(GradeResultRow)).scalars().all()

    assert n_results == 2 * len(recipe.regions)
    assert codes and all(c.batch == "LOT42" for c in codes)
    assert codes[0].gtin == "09506000134352"
    assert grades and all(g.certified is False for g in grades)


def test_recipe_save_and_approve_is_audited(tmp_path):
    from vis.db.users import AuthError, UserService

    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))

    repo = RecipeRepository(sf)
    recipe_id = repo.save_draft(build_code_demo_recipe(), user_id=eng_id)

    # engineer lacks recipe.approve
    with pytest.raises(PermissionError):
        repo.approve(recipe_id, user_id=eng_id, password="Secret123")
    # wrong password blocks the e-signature
    with pytest.raises(AuthError):
        repo.approve(recipe_id, user_id=qa_id, password="WRONG")

    repo.approve(recipe_id, user_id=qa_id, password="Secret123", meaning="QA approved")

    with sf() as s:
        recipe = s.get(Recipe, recipe_id)
        assert recipe.status == "approved"
        assert recipe.approved_by == qa_id
        assert recipe.approved_signature_id is not None
        ok, _ = AuditService(s).verify_chain()
        assert ok


def test_save_draft_requires_permission(tmp_path):
    from vis.db.users import UserService

    sf = _sf(tmp_path)
    users = UserService(sf)
    users.seed_roles()
    op_id = users.create_user("op", "Secret123", roles=("operator",))  # no recipe.create
    repo = RecipeRepository(sf)
    with pytest.raises(PermissionError):
        repo.save_draft(build_code_demo_recipe(), user_id=op_id)
