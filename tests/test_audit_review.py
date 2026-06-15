"""Audit-trail review by exception: anomaly taxonomy, e-signed incremental
review, segregation of duties, chain check, and the batch-release gate."""

import pytest

from vis.cli import build_code_demo_recipe
from vis.db.audit_review import classify
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.reconciliation import ReconciliationService
from vis.db.store import RecipeRepository, ResultStore
from vis.db.users import AuthError, UserService
from vis.engine.aggregator import RegionResult
from vis.tools.base import ToolResult


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))      # can review
    op = users.create_user("op", "Secret123", roles=("operator",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    return sf, qa, op, rr, rid


def _feed(sf, batch_id, good, bad):
    store = ResultStore(sf, batch_id=batch_id)
    fid = 0
    for _ in range(good):
        fid += 1
        store.on_result(RegionResult(fid, "c", "r", "l", True, [ToolResult("c", True, "x", None, 1.0)]))
    for _ in range(bad):
        fid += 1
        store.on_result(RegionResult(fid, "c", "r", "l", False, [ToolResult("c", False, "x", None, 0.0)]))


class _E:
    def __init__(self, action, after=None):
        self.action, self.after, self.before = action, after or {}, {}


def test_taxonomy_severity():
    assert classify(_E("time.anomaly"))[1] == "critical"
    assert classify(_E("batch.close", {"override_reason": "x"}))[0] == "RECONCILIATION_OVERRIDE"
    assert classify(_E("challenge.run", {"result": "fail"}))[1] == "critical"
    assert classify(_E("challenge.run", {"result": "pass"})) is None
    assert classify(_E("recipe.approve"))[1] == "major"
    assert classify(_E("user.create"))[1] == "major"
    assert classify(_E("font.train"))[1] == "minor"
    assert classify(_E("batch.start")) is None  # routine, unflagged


def test_review_signs_and_advances_watermark(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    from vis.db.audit_review import AuditReviewService

    batch_id = BatchService(sf).start(rid, "B-001", op)  # op performs
    svc = AuditReviewService(sf)
    assert svc.watermark(batch_id) == 0
    result = svc.review(qa, "Secret123", batch_id)  # qa independently reviews
    assert result["reviewed_to_id"] > 0
    # next review starts above the watermark (incremental)
    assert svc.watermark(batch_id) == result["reviewed_to_id"]


def test_segregation_of_duties(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    from vis.db.audit_review import AuditReviewService

    # qa starts the batch -> qa is a performer in the window -> cannot review it
    batch_id = BatchService(sf).start(rid, "B-001", qa)
    qa2 = UserService(sf).create_user("qa2", "Secret123", roles=("qa_manager",))
    with pytest.raises(ValueError, match="segregation of duties"):
        AuditReviewService(sf).review(qa, "Secret123", batch_id)
    # an independent reviewer can
    assert AuditReviewService(sf).review(qa2, "Secret123", batch_id)["id"] > 0


def test_critical_anomaly_needs_disposition(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    from vis.db.audit_review import AuditReviewService

    batch_id = BatchService(sf).start(rid, "B-001", op)  # op performs
    _feed(sf, batch_id, 90, 5)
    ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    # an override creates a CRITICAL reconciliation-override audit entry
    BatchService(sf).close(batch_id, qa, "Secret123", override_reason="setup loss")

    # a fresh batch window review that includes the critical entry needs comment
    svc = AuditReviewService(sf)
    reviewer = UserService(sf).create_user("rev", "Secret123", roles=("qa_manager",))
    pending = svc.pending(batch_id)
    crit = [f for f in pending["flags"] if f["severity"] == "critical"]
    assert crit  # the override is flagged critical
    with pytest.raises(ValueError, match="disposition"):
        svc.review(reviewer, "Secret123", batch_id)
    # with a disposition comment it signs off
    dispo = {str(crit[0]["audit_id"]): "reviewed; deviation DEV-12 raised"}
    assert svc.review(reviewer, "Secret123", batch_id, dispositions=dispo)["id"] > 0


def test_release_gate_blocks_on_unreviewed_critical(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    from vis.db.challenge import ChallengeService

    batch_id = BatchService(sf).start(rid, "B-001", op)
    # a FAILED challenge test creates a CRITICAL anomaly
    ChallengeService(sf).run_test(
        op, "Secret123", "batch_start",
        shots=[{"expected_verdict": "reject", "actual_verdict": "pass",
                "reject_io_confirmed": False}], batch_id=batch_id, recipe_id=rid)
    svc = BatchService(sf)
    with pytest.raises(ValueError, match="unreviewed critical"):
        svc.close(batch_id, qa, "Secret123")
    # after an independent audit review, release proceeds
    from vis.db.audit_review import AuditReviewService

    reviewer = UserService(sf).create_user("rev", "Secret123", roles=("qa_manager",))
    flags = AuditReviewService(sf).pending(batch_id)["critical"]
    dispo = {str(f["audit_id"]): "challenge failure investigated" for f in flags}
    AuditReviewService(sf).review(reviewer, "Secret123", batch_id, dispositions=dispo)
    assert svc.close(batch_id, qa, "Secret123") > 0


def test_normal_batch_release_is_ungated(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    # a clean batch (no critical anomalies) closes without a forced review
    batch_id = BatchService(sf).start(rid, "B-001", op)
    _feed(sf, batch_id, 10, 0)
    assert BatchService(sf).close(batch_id, qa, "Secret123") > 0


def test_bad_password_rejected(tmp_path):
    sf, qa, op, rr, rid = _setup(tmp_path)
    from vis.db.audit_review import AuditReviewService

    batch_id = BatchService(sf).start(rid, "B-001", op)
    with pytest.raises(AuthError):
        AuditReviewService(sf).review(qa, "wrong", batch_id)


def test_audit_review_window(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.audit_review_window import AuditReviewWindow

    sf, qa, op, rr, rid = _setup(tmp_path)
    batch_id = BatchService(sf).start(rid, "B-001", op)
    win = AuditReviewWindow(sf, qa, batch_id=batch_id)
    win._password.setText("Secret123")
    win._sign()
    assert "reviewed and signed" in win._status.text()
