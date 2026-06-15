"""Challenge-test (known-bad sample verification) service + line-start gate."""

import pytest

from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.challenge import ChallengeService
from vis.db.store import RecipeRepository
from vis.db.users import AuthError, UserService


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    op = users.create_user("op", "Secret123", roles=("operator",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    return sf, qa, op, rid


def test_starter_defects_seeded(tmp_path):
    sf, *_ = _setup(tmp_path)
    svc = ChallengeService(sf)
    svc.ensure_starter_defects()
    svc.ensure_starter_defects()  # idempotent
    codes = {d["code"] for d in svc.list_defects()}
    assert {"NO_CODE", "WRONG_GTIN", "DUP_SERIAL"} <= codes


def test_passing_test_unlocks_line(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    result = svc.run_test(
        qa, "Secret123", "line_start",
        shots=[
            {"label": "no code", "expected_verdict": "reject",
             "actual_verdict": "reject", "reject_io_confirmed": True},
            {"label": "wrong gtin", "expected_verdict": "reject",
             "actual_verdict": "reject", "reject_io_confirmed": True},
        ],
        recipe_id=rid,
    )
    assert result["result"] == "pass" and result["line_gate_action"] == "unlocked"
    gate = svc.latest_pass(recipe_id=rid, within_hours=24)
    assert gate is not None and gate["id"] == result["id"]


def test_failing_test_blocks_line(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    # the system did NOT reject the bad sample -> the challenge fails
    result = svc.run_test(
        qa, "Secret123", "batch_start",
        shots=[{"label": "expired date", "expected_verdict": "reject",
                "actual_verdict": "pass", "reject_io_confirmed": False}],
        recipe_id=rid,
    )
    assert result["result"] == "fail" and result["line_gate_action"] == "blocked"
    assert svc.latest_pass(recipe_id=rid) is None


def test_reject_io_must_confirm(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    # system flagged reject but the 24V actuator did NOT fire -> fail
    result = svc.run_test(
        qa, "Secret123", "line_start",
        shots=[{"label": "no code", "expected_verdict": "reject",
                "actual_verdict": "reject", "reject_io_confirmed": False}],
        recipe_id=rid,
    )
    assert result["result"] == "fail"


def test_known_good_control_must_pass(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    # a good control that the system wrongly rejected (over-rejection) -> fail
    result = svc.run_test(
        qa, "Secret123", "line_start",
        shots=[
            {"label": "bad", "expected_verdict": "reject",
             "actual_verdict": "reject", "reject_io_confirmed": True},
            {"label": "good control", "expected_verdict": "pass",
             "actual_verdict": "reject", "reject_io_confirmed": True},
        ],
        recipe_id=rid,
    )
    assert result["result"] == "fail"


def test_bad_password_rejected(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    with pytest.raises(AuthError):
        ChallengeService(sf).run_test(
            qa, "wrong", "line_start",
            shots=[{"expected_verdict": "reject", "actual_verdict": "reject",
                    "reject_io_confirmed": True}])


def test_operator_can_run_but_unprivileged_cannot(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    # operators run challenge tests (they have batch.manage)
    result = svc.run_test(
        op, "Secret123", "line_start",
        shots=[{"expected_verdict": "reject", "actual_verdict": "reject",
                "reject_io_confirmed": True}], recipe_id=rid)
    assert result["result"] == "pass"
    # a user with no roles cannot
    noone = UserService(sf).create_user("noone", "Secret123", roles=())
    with pytest.raises(PermissionError):
        svc.run_test(noone, "Secret123", "line_start",
                     shots=[{"expected_verdict": "reject", "actual_verdict": "reject",
                             "reject_io_confirmed": True}])


def test_latest_pass_respects_time_window(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    result = svc.run_test(
        qa, "Secret123", "line_start",
        shots=[{"expected_verdict": "reject", "actual_verdict": "reject",
                "reject_io_confirmed": True}], recipe_id=rid)
    assert svc.latest_pass(recipe_id=rid, within_hours=24) is not None
    # backdate the completion far in the past -> outside the window
    from vis.db.models import ChallengeTest
    with sf() as s:
        t = s.get(ChallengeTest, result["id"])
        t.completed_at = "2000-01-01T00:00:00+00:00"
        s.commit()
    assert svc.latest_pass(recipe_id=rid, within_hours=24) is None


def test_list_tests_records_shots(tmp_path):
    sf, qa, op, rid = _setup(tmp_path)
    svc = ChallengeService(sf)
    svc.run_test(qa, "Secret123", "shift_start",
                 shots=[{"label": "no code", "expected_verdict": "reject",
                         "actual_verdict": "reject", "reject_io_confirmed": True}],
                 recipe_id=rid)
    tests = svc.list_tests()
    assert len(tests) == 1 and tests[0]["result"] == "pass"
    assert tests[0]["shots"][0]["label"] == "no code"


def test_challenge_dialog_runs_and_signs(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.challenge_window import ChallengeDialog

    sf, qa, op, rid = _setup(tmp_path)
    dlg = ChallengeDialog(sf, qa, recipe_id=rid)
    # mark every defect as correctly rejected + ejector fired
    for rejected, fired in dlg._checks:
        rejected.setChecked(True)
        fired.setChecked(True)
    dlg._password.setText("Secret123")
    dlg._run()
    assert dlg.result is not None and dlg.result["result"] == "pass"


def test_start_gate_blocks_without_passing_test(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.main_window import MainWindow

    sf, qa, op, rid = _setup(tmp_path)
    # gate disabled (0 h) -> start is never blocked
    win = MainWindow(username="qa", recipe=build_code_demo_recipe(),
                     camera_factory=lambda *a: None, session_factory=sf, user_id=qa,
                     require_challenge_hours=0)
    assert win._challenge_gate_ok(rid) is True
    # gate enabled but no passing test yet -> the service reports no valid gate
    win._require_challenge_hours = 8
    assert ChallengeService(sf).latest_pass(recipe_id=rid, within_hours=8) is None
    # after a passing test, the gate opens (no modal -- a valid test exists)
    ChallengeService(sf).run_test(
        qa, "Secret123", "line_start",
        shots=[{"expected_verdict": "reject", "actual_verdict": "reject",
                "reject_io_confirmed": True}], recipe_id=rid)
    assert win._challenge_gate_ok(rid) is True
