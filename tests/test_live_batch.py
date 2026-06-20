import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("qrcode")
pytest.importorskip("PySide6")

from sqlalchemy import func, select  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.models import Batch, InspectionResult  # noqa: E402
from vis.db.store import RecipeRepository  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_live_window_runs_selected_recipe_as_a_batch(tmp_path):
    _qapp()
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa_id = users.create_user("qa", "Secret123", roles=("qa_manager",))

    repo = RecipeRepository(sf)
    rid = repo.save_draft(build_code_demo_recipe(), user_id=qa_id)
    repo.approve(rid, qa_id, "Secret123", "released")

    from vis.hmi.main_window import MainWindow

    def factory(camera_id, settings, recipe):
        return SimulatedCodeCamera(camera_id, recipe, num_frames=2, defect_rate=0.0, seed=0)

    win = MainWindow(
        username="qa",
        recipe=build_code_demo_recipe(),
        camera_factory=factory,
        session_factory=sf,
        user_id=qa_id,
    )
    # create a batch order, then select it on the line (strict batch-driven flow)
    from vis.db.batches import BatchService

    bid = BatchService(sf).start(rid, "B-LIVE-01", qa_id)
    win._reload_open_batches()
    idx = win._batch_combo.findData(bid)
    assert idx > 0
    win._batch_combo.setCurrentIndex(idx)

    win.start()
    batch_id = win._batch_id
    assert batch_id == bid
    if win._runner is not None:
        win._runner.join()
    win._refresh()
    win.stop()  # stops acquisition; batch stays open until released

    with sf() as s:
        n = s.execute(
            select(func.count()).select_from(InspectionResult).where(
                InspectionResult.batch_id == batch_id
            )
        ).scalar()
        batch = s.get(Batch, batch_id)
    assert n > 0
    assert batch is not None and batch.status == "open"
    assert win._batch_id == batch_id and win._close_batch.isEnabled()
