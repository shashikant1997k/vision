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


def test_station_config_requires_permission(tmp_path):
    sf, _, op_id = _setup(tmp_path)
    repo = StationRepository(sf)
    with pytest.raises(PermissionError):
        repo.create_station("nope", user_id=op_id)  # operator lacks station.manage
