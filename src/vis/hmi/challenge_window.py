"""Challenge-test dialog — the operator runs known-bad samples and records, per
shot, whether the system rejected and the 24V ejector fired, then e-signs. A
pass unlocks the line; a fail blocks it (docs/14)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.challenge import TRIGGERS, ChallengeService


class ChallengeDialog(QDialog):
    """Run a challenge test. Pre-seeds a shot row per active defect-library item;
    the operator marks the actual verdict + reject-confirmation for each."""

    def __init__(self, session_factory, user_id, recipe_id=None, batch_id=None,
                 station=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Challenge test — verify the reject system")
        self._svc = ChallengeService(session_factory)
        self._svc.ensure_starter_defects()
        self._user_id = user_id
        self._recipe_id = recipe_id
        self._batch_id = batch_id
        self._station = station
        self.result: dict | None = None

        self._trigger = QComboBox()
        for t in TRIGGERS:
            self._trigger.addItem(t.replace("_", " "), t)
        top = QHBoxLayout()
        top.addWidget(QLabel("Trigger"))
        top.addWidget(self._trigger)
        top.addStretch(1)

        self._defects = self._svc.list_defects()
        self._table = QTableWidget(len(self._defects), 4)
        self._table.setHorizontalHeaderLabels(
            ["Defect sample", "Expected", "System rejected?", "Ejector fired?"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._checks: list[tuple[QCheckBox, QCheckBox]] = []
        for r, d in enumerate(self._defects):
            self._table.setItem(r, 0, QTableWidgetItem(f"{d['code']} — {d['description']}"))
            self._table.setItem(r, 1, QTableWidgetItem(d["expected_verdict"]))
            rejected = QCheckBox()
            fired = QCheckBox()
            self._wrap(r, 2, rejected)
            self._wrap(r, 3, fired)
            self._checks.append((rejected, fired))

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("password (electronic signature)")
        run = QPushButton("Run && sign")
        run.setProperty("variant", "primary")
        run.clicked.connect(self._run)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._status = QLabel("Present each known-bad sample, then tick what the system did.")
        self._status.setWordWrap(True)
        actions = QHBoxLayout()
        actions.addWidget(self._password, 1)
        actions.addWidget(run)
        actions.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status)
        layout.addLayout(actions)

    def _wrap(self, row, col, widget) -> None:
        from PySide6.QtCore import Qt

        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.addWidget(widget)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        self._table.setCellWidget(row, col, holder)

    def _run(self) -> None:
        shots = []
        for d, (rejected, fired) in zip(self._defects, self._checks):
            shots.append({
                "defect_item_id": d["id"],
                "label": d["code"],
                "expected_verdict": d["expected_verdict"],
                "actual_verdict": "reject" if rejected.isChecked() else "pass",
                "reject_io_confirmed": fired.isChecked(),
            })
        try:
            self.result = self._svc.run_test(
                self._user_id, self._password.text(), self._trigger.currentData(),
                shots, recipe_id=self._recipe_id, batch_id=self._batch_id,
                station=self._station,
            )
        except Exception as exc:
            self._status.setText(f"Failed: {exc}")
            return
        if self.result["result"] == "pass":
            self.accept()
        else:
            self._status.setText(
                "CHALLENGE FAILED — the line stays blocked. Investigate the reject "
                "system and raise a deviation."
            )
