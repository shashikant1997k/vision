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


def test_match_mode_build_read_roundtrip():
    from vis.hmi.teach_model import build_config, read_config

    cases = [
        ("code_verify", "Fixed value", "0109506..."),
        ("code_verify", "Any readable code", ""),
        ("code_verify", "Matches pattern", r"\d{14}"),
        ("ocv_text", "Fixed value", "LOT42"),
        ("ocv_text", "Contains text", "LOT"),
        ("ocv_text", "Matches pattern", r"\d{4}/\d{2}"),
    ]
    for tool_type, mode, value in cases:
        config = build_config(tool_type, mode, value)
        assert read_config(tool_type, config) == {
            "mode": mode, "value": value, "rotation": 0, "field": ""
        }


def test_build_read_rotation_and_batch_field():
    from vis.hmi.teach_model import build_config, read_config

    rotated = build_config("ocv_text", "Fixed value", "LOT42", rotation=90)
    assert rotated["rotation"] == 90
    assert read_config("ocv_text", rotated)["rotation"] == 90

    batch = build_config("ocv_text", "Matches batch field", "", field="lot")
    assert batch == {"match": "batch_field", "field": "lot", "uppercase": True}
    info = read_config("ocv_text", batch)
    assert info["mode"] == "Matches batch field" and info["field"] == "lot"


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


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _qa_setup(tmp_path):
    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.users import UserService

    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))
    return sf, qa_id


def test_display_to_image_roi_mapping():
    from vis.hmi.roi_label import display_to_image_roi

    # label 800x600, img 400x300 -> scale 2, no letterbox
    assert display_to_image_roi((0, 0), (200, 200), (800, 600), (400, 300)) == (0, 0, 100, 100)


def test_display_to_image_roi_clamps_to_image():
    from vis.hmi.roi_label import display_to_image_roi

    assert display_to_image_roi((-50, -50), (9999, 9999), (800, 600), (400, 300)) == (0, 0, 400, 300)


def test_approve_dialog_collects_values():
    pytest.importorskip("PySide6")
    _qapp()
    from vis.hmi.approve_dialog import ApproveDialog

    dlg = ApproveDialog()
    dlg._password.setText("pw")
    dlg._meaning.setText("released")
    dlg._accept()
    assert dlg.password_value == "pw" and dlg.meaning_value == "released"


def _teach_window(sf, user_id):
    from vis.hmi.teach_window import TeachWindow

    return TeachWindow(
        user_id=user_id, reference_image=_reference_frame().image,
        session_factory=sf, reject_lanes=["lane1", "lane2"],
    )


def test_teach_starts_with_a_default_product():
    pytest.importorskip("PySide6")
    _qapp()
    win = _teach_window(None, 1)
    assert len(win._model.regions) == 1  # full-frame product ready to use


def test_teach_rotate_image():
    pytest.importorskip("PySide6")
    _qapp()
    win = _teach_window(None, 1)
    h, w = win._reference.shape[:2]
    win._rotate_image()
    assert win._model.image_rotation == 90
    # default product resized to the rotated frame (w<->h swapped)
    assert (win._model.regions[0].roi.w, win._model.regions[0].roi.h) == (h, w)


def test_teach_adjust_roi_with_handles(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)
    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    win._selected = ("tool", 0, 0)
    win._on_roi_adjusted(50, 60, 200, 200)  # dragged handles -> new ROI
    roi = win._model.regions[0].tools[0].roi
    assert (roi.x, roi.y, roi.w, roi.h) == (50, 60, 200, 200)


def test_teach_image_bank_and_test_all(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.teach_window import TeachWindow

    recipe = build_code_demo_recipe()
    bank = [f.image for f in SimulatedCodeCamera("ref", recipe, num_frames=4, defect_rate=0.0).frames()]
    win = TeachWindow(
        user_id=qa_id, reference_image=bank[0], reference_images=bank,
        session_factory=sf, reject_lanes=["lane1", "lane2"],
    )
    assert len(win._bank) == 4
    assert win._img_label.text() == "Image 1 / 4"
    win._next_image()
    assert win._reference_index == 1 and win._img_label.text() == "Image 2 / 4"

    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    win._test_all()
    assert "captured image" in win._status.text()


def test_teach_add_inspection_by_drawing(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)

    win._arm_tool("code_verify")           # pick "Read Code" from the palette
    win._on_roi_drawn(30, 30, 300, 300)    # draw its box on the image

    tools = win._model.regions[0].tools
    assert len(tools) == 1
    assert tools[0].tool_type == "code_verify"
    assert (tools[0].roi.w, tools[0].roi.h) == (300, 300)
    assert win._selected == ("tool", 0, 0)  # the new inspection is selected


def test_teach_delete_inspection(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)
    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    win._selected = ("tool", 0, 0)
    win._delete_selected()
    assert win._model.regions[0].tools == []


def test_teach_draw_after_deleting_all_products_does_not_crash(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)
    # delete the default product, leaving none
    win._selected = ("region", 0)
    win._delete_selected()
    assert win._model.regions == []
    # drawing an inspection now must auto-create a product (regression: IndexError)
    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    assert len(win._model.regions) == 1
    assert len(win._model.regions[0].tools) == 1


def test_teach_batch_field_and_rotation(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)
    win._arm_tool("ocv_text")
    win._on_roi_drawn(10, 10, 80, 24)

    win._t_mode.setCurrentText("Matches batch field")  # fed before every batch
    config = win._model.regions[0].tools[0].config
    assert config["match"] == "batch_field" and config["field"] == "lot"

    win._t_rotation.setCurrentText("90°")  # sideways print
    assert win._model.regions[0].tools[0].config.get("rotation") == 90


def test_teach_variable_code_pattern(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    win = _teach_window(sf, qa_id)
    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    win._t_mode.setCurrentText("Matches pattern")
    win._t_value.setText(r"\d{2}.*")  # variable: any code starting with two digits
    config = win._model.regions[0].tools[0].config
    assert config.get("pattern") == r"\d{2}.*" and "expected_data" not in config


def test_teach_draw_test_save_approve(tmp_path):
    pytest.importorskip("PySide6")
    _qapp()
    sf, qa_id = _qa_setup(tmp_path)
    from vis.db.models import Recipe as RecipeRow
    from vis.db.store import RecipeRepository

    win = _teach_window(sf, qa_id)
    win._arm_tool("code_verify")
    win._on_roi_drawn(30, 30, 300, 300)
    win._t_mode.setCurrentText("Fixed value")     # static code
    win._t_value.setText(_gs1("SN0001"))           # edit in the properties panel
    assert win._model.regions[0].tools[0].config.get("expected_data") == _gs1("SN0001")

    win._test()
    assert "passed" in win._status.text()
    win._save()
    assert win._saved_recipe_id is not None and win._approve_btn.isEnabled()

    RecipeRepository(sf).approve(win._saved_recipe_id, qa_id, "Secret123", "released")
    with sf() as s:
        assert s.get(RecipeRow, win._saved_recipe_id).status == "approved"
    win._save()
    assert "Saved draft" in win._status.text()
