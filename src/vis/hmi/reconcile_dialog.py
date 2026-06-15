"""Batch reconciliation entry dialog — the operator enters issued/sample/
recovered/destroyed/reject-bin figures; the dialog shows the live reconciliation
(yield %, reconciliation %, unaccounted, duplicates) before the release signature."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ..db.reconciliation import ReconciliationService


class ReconcileDialog(QDialog):
    def __init__(self, session_factory, batch_id: int, user_id: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch reconciliation")
        self._svc = ReconciliationService(session_factory)
        self._batch_id = batch_id
        self._user_id = user_id

        current = self._svc.compute(batch_id)

        self._units_in = self._spin(current.get("units_in") or current.get("total_inspected", 0))
        self._samples = self._spin(0)
        self._recovered = self._spin(0)
        self._destroyed = self._spin(0)
        self._reject_bin = self._spin(current.get("rejected", 0))
        self._target_rate = self._spin(0)
        self._target_rate.setSuffix(" units/min")

        form = QFormLayout()
        form.addRow("Units in (issued)", self._units_in)
        form.addRow("Samples removed", self._samples)
        form.addRow("Recovered / reworked", self._recovered)
        form.addRow("Destroyed", self._destroyed)
        form.addRow("Reject-bin physical count", self._reject_bin)
        form.addRow("Target rate (for OEE)", self._target_rate)

        self._readout = QLabel()
        self._readout.setWordWrap(True)
        for spin in (self._units_in, self._samples, self._recovered, self._destroyed, self._reject_bin):
            spin.valueChanged.connect(self._recompute)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._readout)
        layout.addWidget(buttons)
        self._figures = {}
        self._recompute()

    def _spin(self, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 100_000_000)
        spin.setValue(int(value or 0))
        return spin

    def _current_figures(self) -> dict:
        return {
            "units_in": self._units_in.value(),
            "samples_removed": self._samples.value(),
            "recovered": self._recovered.value(),
            "destroyed": self._destroyed.value(),
            "reject_bin_count": self._reject_bin.value(),
        }

    def _recompute(self) -> None:
        # preview without persisting: store then compute (cheap, single batch)
        recon = self._svc.set_figures(self._batch_id, self._user_id, self._current_figures())
        verdict = "✓ reconciles" if recon["reconciled"] else "✗ does not reconcile"
        dup = len(recon["duplicate_serials"])
        self._readout.setText(
            f"Good {recon['good']}  Rejected {recon['rejected']}  "
            f"Accounted {recon['accounted']}  Unaccounted {recon['unaccounted']}\n"
            f"Yield {recon['yield_pct']}%   Reconciliation {recon['reconciliation_pct']}%   "
            f"Reject-bin Δ {recon['reject_bin_delta']}   Duplicates {dup}\n{verdict}"
        )
        self._figures = recon

    def _save(self) -> None:
        self._svc.set_figures(self._batch_id, self._user_id, self._current_figures())
        if self._target_rate.value() > 0:
            from ..db.oee import OEEService

            OEEService(self._svc._sf).set_target_rate(self._batch_id, self._target_rate.value())
        self.accept()

    def reconciliation(self) -> dict:
        return self._figures
