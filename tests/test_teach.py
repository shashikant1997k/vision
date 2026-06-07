import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from vis.common.types import ROI  # noqa: E402
from vis.hmi.teach_model import TeachModel, tool_config  # noqa: E402

pytest.importorskip("qrcode")

from vis.cli import _gs1, build_code_demo_recipe  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _reference_frame():
    recipe = build_code_demo_recipe()
    return next(SimulatedCodeCamera("ref", recipe, num_frames=1, defect_rate=0.0).frames())


def test_teach_tool_config_by_type():
    assert tool_config("code_verify", "ABC")["expected_data"] == "ABC"
    assert tool_config("ocv_text", "LOT42")["expected"] == "LOT42"


def test_teach_build_and_test_passes():
    frame = _reference_frame()
    model = TeachModel("Demo Tablets", "taught-demo")
    i = model.add_region("Product 1", ROI(0, 0, 360, 480), "lane1")
    model.add_tool(
        i, "code1", "code_verify", ROI(30, 30, 300, 300), tool_config("code_verify", _gs1("SN0001"))
    )
    results = model.test(frame.image)
    assert results and all(r.passed for r in results)


def test_teach_mismatch_fails():
    frame = _reference_frame()
    model = TeachModel("Demo", "t")
    i = model.add_region("P1", ROI(0, 0, 360, 480), "lane1")
    model.add_tool(
        i, "code1", "code_verify", ROI(30, 30, 300, 300), tool_config("code_verify", _gs1("WRONG"))
    )
    assert not all(r.passed for r in model.test(frame.image))


def test_teach_save_draft(tmp_path):
    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.models import Recipe as RecipeRow
    from vis.db.store import RecipeRepository
    from vis.db.users import UserService

    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))

    model = TeachModel("Demo", "taught")
    i = model.add_region("P1", ROI(0, 0, 360, 480), "lane1")
    model.add_tool(i, "code1", "code_verify", ROI(30, 30, 300, 300), tool_config("code_verify", ""))
    recipe_id = RecipeRepository(sf).save_draft(model.to_recipe(), user_id=eng_id)

    with sf() as s:
        rec = s.get(RecipeRow, recipe_id)
        assert rec is not None and rec.status == "draft"


def test_teach_window_smoke(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.users import UserService
    from vis.hmi.teach_window import TeachWindow

    QApplication.instance() or QApplication([])
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))

    win = TeachWindow(
        user_id=eng_id,
        reference_image=_reference_frame().image,
        session_factory=sf,
        reject_lanes=["lane1", "lane2"],
    )
    win._region_name.setText("Product 1")
    win._rw.setValue(360)
    win._rh.setValue(480)
    win._add_region()

    win._tool_type.setCurrentText("code_verify")
    win._tx.setValue(30)
    win._ty.setValue(30)
    win._tw.setValue(300)
    win._th.setValue(300)
    win._expected.setText(_gs1("SN0001"))
    win._add_tool()

    win._test()
    assert "passed" in win._status.text()
    win._save()
    assert "Saved draft" in win._status.text()
