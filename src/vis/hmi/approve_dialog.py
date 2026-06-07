from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class ApproveDialog(QDialog):
    """Collects the password + meaning for an electronic-signature approval."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Approve recipe — electronic signature")
        self.password_value: str | None = None
        self.meaning_value: str | None = None

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._meaning = QLineEdit("Approved for production")

        form = QFormLayout()
        form.addRow("Re-enter password", self._password)
        form.addRow("Meaning", self._meaning)

        ok = QPushButton("Sign && approve")
        ok.clicked.connect(self._accept)
        self._password.returnPressed.connect(self._accept)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok)

    def _accept(self) -> None:
        self.password_value = self._password.text()
        self.meaning_value = self._meaning.text().strip() or "Approved"
        self.accept()
