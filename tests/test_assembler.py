import pytest
from sqlalchemy import func, select

from vis.camera import CameraSettings
from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.models import Batch, CameraAssignment, FrameCapture, InspectionResult
from vis.db.stations import StationRepository
from vis.db.users import UserService
from vis.engine.pool import SyncPool
from vis.io import SimulatedIO
from vis.runtime.archive import FrameArchiver
from vis.runtime.assembler import RuntimeAssembler

pytest.importorskip("qrcode")


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))
    repo = StationRepository(sf)
    sid = repo.create_station("S1", user_id=eng_id)
    repo.add_camera(sid, "cam1", user_id=eng_id, settings=CameraSettings(exposure_us=4000))
    repo.add_reject_output(sid, "lane1", channel=1, user_id=eng_id)
    repo.add_reject_output(sid, "lane2", channel=2, user_id=eng_id)
    return sf, eng_id, sid


def _factory(defect_rate):
    from vis.engine.sim import SimulatedCodeCamera

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=3, defect_rate=defect_rate, seed=0)

    return factory


def test_assemble_drives_reject_from_persisted_config(tmp_path):
    sf, _, sid = _setup(tmp_path)
    recipe = build_code_demo_recipe()
    io = SimulatedIO()
    asm = RuntimeAssembler(sf, camera_factory=_factory(1.0), reject_io=io)
    runner = asm.build_runner(sid, [("cam1", recipe)], SyncPool())
    runner.run()

    expected = 3 * len(recipe.regions)
    assert runner.reject_handler.fired == expected
    assert io.pulse_count(1) + io.pulse_count(2) == expected


def test_assemble_with_batch_persists_results_and_assignment(tmp_path):
    sf, eng_id, sid = _setup(tmp_path)
    recipe = build_code_demo_recipe()
    with sf() as s:
        batch = Batch(batch_no="B1", status="open")
        s.add(batch)
        s.flush()
        bid = batch.id
        s.commit()

    asm = RuntimeAssembler(sf, camera_factory=_factory(0.0))
    runner = asm.build_runner(sid, [("cam1", recipe)], SyncPool(), batch_id=bid, user_id=eng_id)
    runner.run()

    with sf() as s:
        n = s.execute(
            select(func.count()).select_from(InspectionResult).where(
                InspectionResult.batch_id == bid
            )
        ).scalar()
        assignments = s.execute(
            select(CameraAssignment).where(CameraAssignment.batch_id == bid)
        ).scalars().all()
    assert n == 3 * len(recipe.regions)
    assert len(assignments) == 1 and assignments[0].recipe_ref == "code-demo"


def test_frame_archiver_saves_fail_frames(tmp_path):
    sf, _, sid = _setup(tmp_path)
    recipe = build_code_demo_recipe()
    archiver = FrameArchiver(sf, str(tmp_path / "imgs"), policy="fails")
    asm = RuntimeAssembler(sf, camera_factory=_factory(1.0))
    runner = asm.build_runner(sid, [("cam1", recipe)], SyncPool(), on_frame=archiver.on_frame)
    runner.run()

    with sf() as s:
        captures = s.execute(select(FrameCapture)).scalars().all()
    assert captures
    assert all(c.image_ref for c in captures)  # all frames had a reject -> images saved
