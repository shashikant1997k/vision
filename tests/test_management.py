import pytest

from vis.cli import build_code_demo_recipe
from vis.db.audit import AuditService
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.products import ProductRepository
from vis.db.store import RecipeRepository
from vis.db.users import UserService


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    admin = users.create_user("admin", "Secret123", roles=("admin",))
    op = users.create_user("op1", "Secret123", roles=("operator",))
    return sf, users, admin, op


def test_user_management(tmp_path):
    sf, users, admin, op = _setup(tmp_path)
    listed = {u["username"]: u for u in users.list_users()}
    assert listed["op1"]["roles"] == ["operator"] and listed["op1"]["active"]
    assert "admin" in users.list_roles()

    # admin creates a user, changes roles, resets password, deactivates
    uid = users.admin_create_user(admin, "eng1", "Secret123", "Engineer One", ("engineer",))
    users.set_roles(admin, uid, ("engineer", "qa_manager"))
    assert set(next(u for u in users.list_users() if u["id"] == uid)["roles"]) == {"engineer", "qa_manager"}

    users.reset_password(admin, uid, "NewPass123")
    assert users.authenticate("eng1", "NewPass123") == uid

    users.set_active(admin, uid, False)
    with pytest.raises(Exception):
        users.authenticate("eng1", "NewPass123")  # inactive

    # an operator may not manage users
    with pytest.raises(PermissionError):
        users.admin_create_user(op, "x", "Secret123")


def test_product_management(tmp_path):
    sf, users, admin, op = _setup(tmp_path)
    repo = ProductRepository(sf)
    repo.create_product(admin, "TAB500", "Tablets 500mg")
    products = repo.list_products()
    assert any(p["code"] == "TAB500" and p["name"] == "Tablets 500mg" for p in products)
    with pytest.raises(ValueError):
        repo.create_product(admin, "TAB500")  # duplicate code
    with pytest.raises(PermissionError):
        repo.create_product(op, "OPX")  # operator lacks recipe.create


def test_batch_listing(tmp_path):
    sf, users, admin, op = _setup(tmp_path)
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    BatchService(sf).start(rid, "B-001", qa)
    batches = BatchService(sf).list_batches()
    assert batches[0]["batch_no"] == "B-001" and batches[0]["status"] == "open"


def test_audit_log_listing(tmp_path):
    sf, users, admin, op = _setup(tmp_path)
    users.admin_create_user(admin, "eng1", "Secret123", roles=("engineer",))
    with sf() as s:
        entries = AuditService(s).list_entries()
    actions = {e["action"] for e in entries}
    assert "user.create" in actions
    assert all("entity" in e and "ts" in e for e in entries)
