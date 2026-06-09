import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")
pytest.importorskip("qrcode")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.batches import BatchService  # noqa: E402
from vis.db.store import RecipeRepository  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.hmi.admin_window import AdminWindow  # noqa: E402


def _qapp():
    return QApplication.instance() or QApplication([])


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    admin = users.create_user("admin", "Secret123", roles=("admin",))
    return sf, users, admin


def test_admin_window_lists_and_creates(tmp_path):
    _qapp()
    sf, users, admin = _setup(tmp_path)
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rid = RecipeRepository(sf).save_draft(build_code_demo_recipe(), user_id=qa)
    RecipeRepository(sf).approve(rid, qa, "Secret123", "released")
    BatchService(sf).start(rid, "B-100", qa)

    win = AdminWindow(sf, admin)
    # users tab lists admin + qa
    assert win._users_table.rowCount() == 2
    # create a product (the demo recipe already created one implicitly)
    win._products.create_product(admin, "TAB", "Tablets")
    win._refresh_products()
    codes = {win._products_table.item(r, 1).text() for r in range(win._products_table.rowCount())}
    assert "TAB" in codes
    # batches tab shows the open batch
    assert win._batches_table.rowCount() == 1
    assert win._batches_table.item(0, 1).text() == "B-100"
    # audit tab populated + chain verifies
    assert win._audit_table.rowCount() > 0
    win._verify_chain()
    assert "VERIFIED" in win._status.text()


def test_admin_window_user_lifecycle(tmp_path):
    _qapp()
    sf, users, admin = _setup(tmp_path)
    win = AdminWindow(sf, admin)
    # create user via the service the window uses, then exercise role/active changes
    uid = users.admin_create_user(admin, "op2", "Secret123", roles=("operator",))
    users.set_roles(admin, uid, ("engineer",))
    users.set_active(admin, uid, False)
    win._refresh_users()
    rows = {win._users_table.item(r, 1).text(): r for r in range(win._users_table.rowCount())}
    assert "op2" in rows
    status = win._users_table.item(rows["op2"], 4).text()
    assert status == "disabled"
