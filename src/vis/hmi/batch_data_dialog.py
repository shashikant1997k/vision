from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QPushButton, QVBoxLayout

from .teach_model import BATCH_FIELDS

_LABELS = dict(BATCH_FIELDS)


class BatchDataDialog(QDialog):
    """Collects the batch number and the per-batch values the recipe expects
    (lot/MFG/expiry/MRP) — the data fed before every batch."""

    def __init__(self, batch_no: str, fields: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Start batch — batch data")
        self._batch_no = QLineEdit(batch_no)
        self._inputs: dict[str, QLineEdit] = {}

        form = QFormLayout()
        form.addRow("Batch no.", self._batch_no)
        for key in fields:
            edit = QLineEdit()
            self._inputs[key] = edit
            form.addRow(_LABELS.get(key, key), edit)

        start = QPushButton("Start batch")
        start.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(start)

    def batch_no(self) -> str:
        return self._batch_no.text().strip()

    def values(self) -> dict:
        return {key: edit.text().strip() for key, edit in self._inputs.items()}
