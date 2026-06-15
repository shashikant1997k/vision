"""Batch reconciliation engine + the close-time reconciliation gate."""

import pytest

from vis.cli import build_code_demo_recipe
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.batches import BatchService
from vis.db.reconciliation import ReconciliationService
from vis.db.serials import SerialRegistry
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
    qa = users.create_user("qa", "Secret123", roles=("qa_manager",))
    rr = RecipeRepository(sf)
    rid = rr.save_draft(build_code_demo_recipe(), user_id=qa)
    rr.approve(rid, qa, "Secret123", "released")
    batch_id = BatchService(sf).start(rid, "B-001", qa)
    return sf, qa, batch_id


def _feed(sf, batch_id, n_good, n_bad):
    store = ResultStore(sf, batch_id=batch_id)
    fid = 0
    for _ in range(n_good):
        fid += 1
        store.on_result(RegionResult(fid, "cam1", "r1", "lane1", True,
                                     [ToolResult("c", True, "x", None, 1.0)]))
    for _ in range(n_bad):
        fid += 1
        store.on_result(RegionResult(fid, "cam1", "r1", "lane1", False,
                                     [ToolResult("c", False, "x", None, 0.0)]))


def test_reconciliation_math(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=95, n_bad=5)
    svc = ReconciliationService(sf)
    recon = svc.set_figures(batch_id, qa, {
        "units_in": 100, "samples_removed": 0, "reject_bin_count": 5})
    assert recon["good"] == 95 and recon["rejected"] == 5
    assert recon["accounted"] == 100 and recon["unaccounted"] == 0
    assert recon["yield_pct"] == 95.0 and recon["reconciliation_pct"] == 100.0
    assert recon["within_tolerance"] is True
    assert recon["reject_bin_delta"] == 0
    assert recon["reconciled"] is True


def test_reconciliation_detects_unaccounted(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=90, n_bad=5)  # 95 accounted
    recon = ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    assert recon["unaccounted"] == 5
    assert recon["within_tolerance"] is False  # 95% vs ±0.5%
    assert recon["reconciled"] is False


def test_reject_bin_delta_flags_actuator_miss(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=98, n_bad=2)
    recon = ReconciliationService(sf).set_figures(batch_id, qa, {
        "units_in": 100, "reject_bin_count": 1})  # only 1 physically in the bin
    assert recon["reject_bin_delta"] == -1  # system says 2, bin has 1


def test_duplicate_serials_block_reconciliation(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=100, n_bad=0)
    reg = SerialRegistry(sf, batch_id)
    reg.check_and_register("SN1")
    reg.check_and_register("SN1")  # duplicate
    recon = ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    assert recon["duplicate_serials"] and recon["reconciled"] is False


def test_close_gate_blocks_unreconciled_batch(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=90, n_bad=5)
    ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    svc = BatchService(sf)
    with pytest.raises(ValueError, match="does not reconcile"):
        svc.close(batch_id, qa, "Secret123")
    # an override reason records a deviation and allows the close
    sig = svc.close(batch_id, qa, "Secret123", override_reason="5 units consumed in line setup")
    assert sig > 0


def test_close_allows_reconciled_batch(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=100, n_bad=0)
    ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    assert BatchService(sf).close(batch_id, qa, "Secret123") > 0


def test_close_without_figures_is_ungated(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=10, n_bad=1)
    # no reconciliation figures entered -> close is not blocked (back-compatible)
    assert BatchService(sf).close(batch_id, qa, "Secret123") > 0


def test_close_still_requires_password(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    with pytest.raises(AuthError):
        BatchService(sf).close(batch_id, qa, "wrong-password")


def test_report_includes_reconciliation(tmp_path):
    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=99, n_bad=1)
    ReconciliationService(sf).set_figures(batch_id, qa, {"units_in": 100})
    from vis.reporting.batch_report import compute_summary, to_html

    with sf() as s:
        summary = compute_summary(s, batch_id)
    assert summary["reconciliation"]["units_in"] == 100
    html = to_html(summary)
    assert "Reconciliation" in html and "Yield %" in html


def test_reconcile_dialog_previews_and_saves(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest = __import__("pytest")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.reconcile_dialog import ReconcileDialog

    sf, qa, batch_id = _setup(tmp_path)
    _feed(sf, batch_id, n_good=95, n_bad=5)
    dlg = ReconcileDialog(sf, batch_id, qa)
    dlg._units_in.setValue(100)
    dlg._recompute()
    recon = dlg.reconciliation()
    assert recon["good"] == 95 and recon["reconciliation_pct"] == 100.0
    assert "reconciles" in dlg._readout.text()
