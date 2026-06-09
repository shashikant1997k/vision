import pytest

from vis.camera import CameraSettings, TriggerConfig, TriggerMode
from vis.db.audit import AuditService
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.stations import StationRepository
from vis.db.users import UserService
from vis.io import RejectController, SimulatedIO


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))
    op_id = users.create_user("op", "Secret123", roles=("operator",))
    return sf, eng_id, op_id


def test_camera_settings_persist_and_update_audited(tmp_path):
    sf, eng_id, _ = _setup(tmp_path)
    repo = StationRepository(sf)
    sid = repo.create_station("Line-1 Station", user_id=eng_id, line="Line-1")
    cid = repo.add_camera(
        sid, "cam1", user_id=eng_id, identifier="192.168.0.10",
        settings=CameraSettings(exposure_us=3000),
    )
    assert repo.camera_settings(cid).exposure_us == 3000

    repo.update_camera_settings(
        cid,
        CameraSettings(exposure_us=8000, trigger=TriggerConfig(mode=TriggerMode.ENCODER)),
        user_id=eng_id,
    )
    restored = repo.camera_settings(cid)
    assert restored.exposure_us == 8000
    assert restored.trigger.mode is TriggerMode.ENCODER

    with sf() as s:
        ok, _ = AuditService(s).verify_chain()
        assert ok


def test_persisted_reject_outputs_drive_the_controller(tmp_path):
    sf, eng_id, _ = _setup(tmp_path)
    repo = StationRepository(sf)
    sid = repo.create_station("S1", user_id=eng_id)
    repo.add_reject_output(sid, "lane1", channel=1, user_id=eng_id, eject_delay_ms=50)
    repo.add_reject_output(sid, "lane2", channel=2, user_id=eng_id)

    configs = repo.reject_output_configs(sid)
    assert {c.name for c in configs} == {"lane1", "lane2"}

    io = SimulatedIO()
    rc = RejectController(configs, io=io, scheduler=lambda d, fn: fn())

    class _RR:
        reject_output = "lane2"

    rc.reject(_RR())
    assert io.pulse_count(2) == 1
    assert io.pulse_count(1) == 0


def test_lighting_config_persist_and_update_audited(tmp_path):
    from vis.camera import LightMode, LightSettings

    sf, eng_id, _ = _setup(tmp_path)
    repo = StationRepository(sf)
    sid = repo.create_station("S1", user_id=eng_id)
    lid = repo.add_light(
        sid, "ringlight", channel=4, user_id=eng_id,
        settings=LightSettings(mode=LightMode.STROBED, brightness=80, strobe_source="Line1"),
    )
    lights = repo.lights(sid)
    assert len(lights) == 1
    _, name, channel, settings = lights[0]
    assert name == "ringlight" and channel == 4
    assert settings.mode is LightMode.STROBED and settings.brightness == 80

    repo.update_light_settings(lid, LightSettings(brightness=50), user_id=eng_id)
    assert repo.lights(sid)[0][3].brightness == 50

    with sf() as s:
        ok, _ = AuditService(s).verify_chain()
        assert ok


def test_station_lookup_by_name(tmp_path):
    sf, eng_id, _ = _setup(tmp_path)
    repo = StationRepository(sf)
    sid = repo.create_station("Line-7", user_id=eng_id)
    assert repo.station_id_by_name("Line-7") == sid
    with pytest.raises(ValueError):
        repo.station_id_by_name("nope")


def test_station_config_requires_permission(tmp_path):
    sf, _, op_id = _setup(tmp_path)
    repo = StationRepository(sf)
    with pytest.raises(PermissionError):
        repo.create_station("nope", user_id=op_id)  # operator lacks station.manage


def test_station_camera_recipe_assignment(tmp_path):
    from vis.cli import build_code_demo_recipe
    from vis.db.store import RecipeRepository

    sf, eng_id, _ = _setup(tmp_path)
    qa = UserService(sf).create_user("qa", "Secret123", roles=("qa_manager",))
    repo = StationRepository(sf)
    rid = RecipeRepository(sf).save_draft(build_code_demo_recipe(), user_id=qa)
    RecipeRepository(sf).approve(rid, qa, "Secret123", "released")

    sid = repo.create_station("Line A", eng_id)
    cam = repo.add_camera(sid, "cam1", eng_id, identifier="192.168.0.10")
    assert (sid, "Line A", "") in repo.list_stations()
    assert repo.camera_recipes(sid) == [(cam, "cam1", None)]

    repo.set_camera_recipe(cam, rid, eng_id)
    assert repo.camera_recipes(sid) == [(cam, "cam1", rid)]


def test_station_window_assigns_recipe(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QFormLayout

    from vis.cli import build_code_demo_recipe
    from vis.db.store import RecipeRepository
    from vis.hmi.station_window import StationConfigWindow

    sf, eng_id, _ = _setup(tmp_path)
    qa = UserService(sf).create_user("qa", "Secret123", roles=("qa_manager",))
    rid = RecipeRepository(sf).save_draft(build_code_demo_recipe(), user_id=qa)
    RecipeRepository(sf).approve(rid, qa, "Secret123", "released")
    repo = StationRepository(sf)
    sid = repo.create_station("Line A", eng_id)
    repo.add_camera(sid, "cam1", eng_id)

    QApplication.instance() or QApplication([])
    win = StationConfigWindow(sf, eng_id)
    combo = win._cam_form.itemAt(0, QFormLayout.FieldRole).widget()
    combo.setCurrentIndex(combo.findData(rid))  # triggers _assign -> persists
    assert repo.camera_recipes(sid)[0][2] == rid
