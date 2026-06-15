"""Audit-trail review-by-exception screen: the reviewer sees only flagged
anomalies (grouped by severity) since the last review, dispositions each
critical one, and e-signs "Audit trail reviewed" (docs/16)."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.audit_review import AuditReviewService

_SEV_COLOR = {"critical": QColor(200, 30, 30), "major": QColor(180, 110, 0)}


class AuditReviewWindow(QMainWindow):
    def __init__(self, session_factory, user_id, batch_id=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Audit-trail review")
        self._svc = AuditReviewService(session_factory)
        self._user_id = user_id
        self._batch_id = batch_id

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Audit #", "Severity", "Anomaly", "Action / time", "Disposition (critical req.)"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("password — e-sign 'Audit trail reviewed'")
        sign = QPushButton("Review && sign")
        sign.setProperty("variant", "primary")
        sign.clicked.connect(self._sign)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._load)
        bar = QHBoxLayout()
        bar.addWidget(self._password, 1)
        bar.addWidget(sign)
        bar.addWidget(refresh)

        self._status = QLabel("")
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        root.addWidget(self._summary)
        root.addWidget(self._table, 1)
        root.addLayout(bar)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._flags: list[dict] = []
        self._load()

    def _load(self) -> None:
        pending = self._svc.pending(self._batch_id)
        self._flags = pending["flags"]
        scope = f"batch #{self._batch_id}" if self._batch_id else "all entries"
        self._summary.setText(
            f"Reviewing {scope}: {pending['entries_total']} entries since the last "
            f"review, {len(self._flags)} flagged ({len(pending['critical'])} critical). "
            "Review by exception — disposition every critical anomaly, then sign."
        )
        self._table.setRowCount(len(self._flags))
        for r, f in enumerate(self._flags):
            cells = [str(f["audit_id"]), f["severity"].upper(), f["code"],
                     f"{f['action']} @ {f['ts'][:19]}"]
            for c, value in enumerate(cells):
                item = QTableWidgetItem(value)
                color = _SEV_COLOR.get(f["severity"])
                if color is not None:
                    item.setForeground(color)
                self._table.setItem(r, c, item)
            self._table.setCellWidget(r, 4, self._disposition_edit(f))

    def _disposition_edit(self, flag) -> QLineEdit:
        edit = QLineEdit()
        if flag["severity"] != "critical":
            edit.setPlaceholderText("(optional)")
        else:
            edit.setPlaceholderText("required — comment / deviation ref")
        flag["_edit"] = edit
        return edit

    def _sign(self) -> None:
        dispositions = {
            str(f["audit_id"]): f["_edit"].text().strip()
            for f in self._flags if f.get("_edit") and f["_edit"].text().strip()
        }
        try:
            result = self._svc.review(
                self._user_id, self._password.text(), self._batch_id, dispositions=dispositions
            )
        except Exception as exc:
            self._status.setText(f"Sign-off failed: {exc}")
            return
        self._status.setText(
            f"Audit trail reviewed and signed (review #{result['id']}, "
            f"{result['flagged']} flags up to entry {result['reviewed_to_id']})."
        )
        self._password.clear()
        self._load()
        self.accept() if isinstance(self, QDialog) else None
