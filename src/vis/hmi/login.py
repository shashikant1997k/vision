from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..db.users import AuthError, UserService


class LoginDialog(QDialog):
    """Authenticates a user via UserService before the HMI opens."""

    def __init__(self, user_service: UserService, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Login")
        self._users = user_service
        self.user_id: int | None = None
        self.username: str | None = None

        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._error = QLabel("")
        self._error.setStyleSheet("color: #c00")

        form = QFormLayout()
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)

        login_button = QPushButton("Log in")
        login_button.clicked.connect(self._try_login)
        self._password.returnPressed.connect(self._try_login)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addWidget(login_button)

    def _try_login(self) -> None:
        try:
            uid = self._users.authenticate(self._username.text().strip(), self._password.text())
        except AuthError as exc:
            self._error.setText(str(exc))
            return
        self.user_id = uid
        self.username = self._username.text().strip()
        self.accept()
