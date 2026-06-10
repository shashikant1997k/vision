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
        self.password = self._password.text()  # for first-login forced change
        self.accept()


class ChangePasswordDialog(QDialog):
    """Forces a password change (first login / default credentials). Won't close
    until the change succeeds."""

    def __init__(self, user_service: UserService, user_id: int, old_password: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change password (required)")
        self._users = user_service
        self._uid = user_id
        self._old = old_password

        info = QLabel(
            "This account is using a default password.\n"
            "Set a new password before continuing (21 CFR Part 11)."
        )
        info.setWordWrap(True)
        self._new = QLineEdit()
        self._new.setEchoMode(QLineEdit.Password)
        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.Password)
        self._error = QLabel("")
        self._error.setStyleSheet("color: #c00")

        form = QFormLayout()
        form.addRow("New password", self._new)
        form.addRow("Confirm", self._confirm)
        button = QPushButton("Change password")
        button.clicked.connect(self._change)
        self._confirm.returnPressed.connect(self._change)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addWidget(button)

    def _change(self) -> None:
        if self._new.text() != self._confirm.text():
            self._error.setText("Passwords do not match.")
            return
        try:
            self._users.change_own_password(self._uid, self._old, self._new.text())
        except Exception as exc:
            self._error.setText(str(exc))
            return
        self.accept()
