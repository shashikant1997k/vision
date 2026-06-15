"""Serial registry: per-batch uniqueness, duplicate detection, reconciliation
counts, and the live-window duplicate-serial alarm."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.serials import SerialRegistry, SerialStatus
from vis.db.users import UserService


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    UserService(sf).seed_roles()
    return sf


def _batch(sf):
    from vis.cli import build_code_demo_recipe
    from vis.db.batches import BatchService
    from vis.db.store import RecipeRepository
    from vis.db.users import UserService

    users = UserService(sf)
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    return BatchService(sf).start(rid, "B-001", qa)


def test_first_sight_new_then_duplicate(tmp_path):
    sf = _sf(tmp_path)
    batch_id = _batch(sf)
    reg = SerialRegistry(sf, batch_id)
    assert reg.check_and_register("SN001").status == SerialStatus.NEW
    assert reg.check_and_register("SN002").status == SerialStatus.NEW
    dup = reg.check_and_register("SN001")
    assert dup.status == SerialStatus.DUPLICATE and dup.seen_count == 2
    again = reg.check_and_register("SN001")
    assert again.seen_count == 3


def test_summary_counts_uniques_and_duplicates(tmp_path):
    sf = _sf(tmp_path)
    batch_id = _batch(sf)
    reg = SerialRegistry(sf, batch_id)
    for s in ("A", "B", "C", "A", "B"):
        reg.check_and_register(s)
    summary = reg.summary()
    assert summary["unique"] == 3
    assert summary["duplicates"] == 2
    assert {d["serial"] for d in summary["duplicate_serials"]} == {"A", "B"}


def test_registry_survives_restart_midbatch(tmp_path):
    sf = _sf(tmp_path)
    batch_id = _batch(sf)
    SerialRegistry(sf, batch_id).check_and_register("SN999")
    # a fresh registry (e.g. after a crash) reloads seen serials from the DB
    reloaded = SerialRegistry(sf, batch_id)
    assert reloaded.check_and_register("SN999").status == SerialStatus.DUPLICATE


def test_status_marking_does_not_override_duplicate(tmp_path):
    sf = _sf(tmp_path)
    batch_id = _batch(sf)
    reg = SerialRegistry(sf, batch_id)
    reg.check_and_register("SN1")
    reg.mark_status("SN1", "good")
    reg.check_and_register("SN1")  # now a duplicate
    reg.mark_status("SN1", "good")  # must not erase duplicate status
    assert reg.summary()["duplicates"] == 1


def test_no_batch_context_still_detects_in_memory():
    reg = SerialRegistry(None, None)
    assert reg.check_and_register("X").status == SerialStatus.NEW
    assert reg.check_and_register("X").status == SerialStatus.DUPLICATE


def test_live_window_raises_duplicate_alarm(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.engine.aggregator import RegionResult
    from vis.hmi.main_window import MainWindow
    from vis.tools.base import ToolResult

    sf = _sf(tmp_path)
    batch_id = _batch(sf)
    admin = UserService(sf).create_user("admin", "Secret123", roles=("admin",))
    from vis.cli import build_code_demo_recipe

    win = MainWindow(username="admin", recipe=build_code_demo_recipe(),
                     camera_factory=lambda *a: None, session_factory=sf, user_id=admin)
    win._serials = SerialRegistry(sf, batch_id)

    def region(passed=True):
        tr = ToolResult("c", passed, "raw", None, 1.0,
                        detail={"fields": {"serial": "SNX", "gtin": "09506000134352"}})
        return RegionResult(1, "cam1", "r1", "lane1", passed, [tr])

    win._on_serial(region())                 # first sight -> NEW
    assert win._duplicate_serials == 0
    win._on_serial(region())                 # second sight -> DUPLICATE alarm
    assert win._duplicate_serials == 1
