from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..db.audit import AuditService
from ..db.batches import BatchService
from ..db.products import ProductRepository
from ..db.users import UserService


class _NewUserDialog(QDialog):
    def __init__(self, roles, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New user")
        self._username = QLineEdit()
        self._fullname = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._roles = {r: QCheckBox(r) for r in roles}
        form = QFormLayout()
        form.addRow("Username", self._username)
        form.addRow("Full name", self._fullname)
        form.addRow("Password", self._password)
        for cb in self._roles.values():
            form.addRow("", cb)
        ok = QPushButton("Create")
        ok.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok)

    def values(self):
        return (
            self._username.text().strip(), self._password.text(), self._fullname.text().strip(),
            tuple(r for r, cb in self._roles.items() if cb.isChecked()),
        )


class AdminWindow(QMainWindow):
    """Admin hub: user management, products, batches & reports, audit log."""

    def __init__(self, session_factory, user_id, report_dir="reports", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Administration")
        self._sf = session_factory
        self._uid = user_id
        self._report_dir = report_dir
        self._users = UserService(session_factory)
        self._products = ProductRepository(session_factory)
        self._batches = BatchService(session_factory)

        from ..security.authz import Perm, permissions_for

        with session_factory() as s:
            perms = permissions_for(s, user_id)

        tabs = QTabWidget()
        self._users_table = self._products_table = None
        self._batches_table = self._audit_table = None
        if Perm.USER_MANAGE in perms:
            tabs.addTab(self._users_tab(), "Users")
        if Perm.RECIPE_CREATE in perms:
            tabs.addTab(self._products_tab(), "Products")
        if Perm.BATCH_MANAGE in perms:
            tabs.addTab(self._batches_tab(), "Batches & reports")
        if Perm.AUDIT_VIEW in perms:
            tabs.addTab(self._audit_tab(), "Audit log")
        self._status = QLabel("")
        root = QVBoxLayout()
        root.addWidget(tabs, 1)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        if self._users_table is not None:
            self._refresh_users()
        if self._products_table is not None:
            self._refresh_products()
        if self._batches_table is not None:
            self._refresh_batches()
        self._refresh_audit()

    @staticmethod
    def _table(headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    @staticmethod
    def _fill(table, rows):
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if c == 0:
                    item.setData(Qt.UserRole, row[0])
                table.setItem(r, c, item)

    def _selected_id(self, table):
        row = table.currentRow()
        if row < 0:
            return None
        return table.item(row, 0).data(Qt.UserRole)

    # ---- Users -------------------------------------------------------------
    def _users_tab(self):
        self._users_table = self._table(["ID", "Username", "Name", "Roles", "Status"])
        new = QPushButton("New user…")
        new.clicked.connect(self._new_user)
        roles = QPushButton("Edit roles…")
        roles.clicked.connect(self._edit_roles)
        pw = QPushButton("Reset password…")
        pw.clicked.connect(self._reset_password)
        toggle = QPushButton("Enable / Disable")
        toggle.clicked.connect(self._toggle_active)
        return self._tab_widget(self._users_table, [new, roles, pw, toggle])

    def _refresh_users(self):
        rows = [
            (u["id"], u["username"], u["full_name"], ", ".join(u["roles"]),
             ("locked" if u["locked"] else ("active" if u["active"] else "disabled")))
            for u in self._users.list_users()
        ]
        self._fill(self._users_table, rows)

    def _new_user(self):
        dlg = _NewUserDialog(self._users.list_roles(), self)
        if dlg.exec() != QDialog.Accepted:
            return
        username, password, full_name, roles = dlg.values()
        if not username or not password:
            self._status.setText("Username and password are required.")
            return
        try:
            self._users.admin_create_user(self._uid, username, password, full_name, roles)
        except Exception as exc:
            self._status.setText(f"Create failed: {exc}")
            return
        self._refresh_users()
        self._refresh_audit()

    def _edit_roles(self):
        uid = self._selected_id(self._users_table)
        if uid is None:
            return
        all_roles = self._users.list_roles()
        current = next((u["roles"] for u in self._users.list_users() if u["id"] == uid), [])
        text, ok = QInputDialog.getText(
            self, "Edit roles", f"Roles (comma-separated from: {', '.join(all_roles)})",
            text=", ".join(current),
        )
        if not ok:
            return
        roles = tuple(r.strip() for r in text.split(",") if r.strip())
        try:
            self._users.set_roles(self._uid, uid, roles)
        except Exception as exc:
            self._status.setText(f"Failed: {exc}")
            return
        self._refresh_users()
        self._refresh_audit()

    def _reset_password(self):
        uid = self._selected_id(self._users_table)
        if uid is None:
            return
        pw, ok = QInputDialog.getText(self, "Reset password", "New password:", echo=QLineEdit.Password)
        if not ok or not pw:
            return
        try:
            self._users.reset_password(self._uid, uid, pw)
            self._status.setText("Password reset.")
        except Exception as exc:
            self._status.setText(f"Failed: {exc}")
        self._refresh_audit()

    def _toggle_active(self):
        uid = self._selected_id(self._users_table)
        if uid is None:
            return
        u = next((x for x in self._users.list_users() if x["id"] == uid), None)
        if u is None:
            return
        try:
            self._users.set_active(self._uid, uid, not (u["active"] and not u["locked"]))
        except Exception as exc:
            self._status.setText(f"Failed: {exc}")
            return
        self._refresh_users()
        self._refresh_audit()

    # ---- Products ----------------------------------------------------------
    def _products_tab(self):
        self._products_table = self._table(["ID", "Code", "Name", "Recipes", "Approved"])
        new = QPushButton("New product…")
        new.clicked.connect(self._new_product)
        return self._tab_widget(self._products_table, [new])

    def _refresh_products(self):
        rows = [(p["id"], p["code"], p["name"], p["recipes"], p["approved"]) for p in self._products.list_products()]
        self._fill(self._products_table, rows)

    def _new_product(self):
        code, ok = QInputDialog.getText(self, "New product", "Product code:")
        if not ok or not code.strip():
            return
        name, ok = QInputDialog.getText(self, "New product", "Product name:", text=code.strip())
        if not ok:
            return
        try:
            self._products.create_product(self._uid, code.strip(), name.strip())
        except Exception as exc:
            self._status.setText(f"Create failed: {exc}")
            return
        self._refresh_products()
        self._refresh_audit()

    # ---- Batches & reports -------------------------------------------------
    def _batches_tab(self):
        self._batches_table = self._table(["ID", "Batch no.", "Product", "Status", "Pass", "Fail", "Started"])
        report = QPushButton("Open report")
        report.clicked.connect(self._open_report)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_batches)
        return self._tab_widget(self._batches_table, [report, refresh])

    def _refresh_batches(self):
        rows = [
            (b["id"], b["batch_no"], b["product"], b["status"], b["passed"], b["failed"], b["started_at"][:19])
            for b in self._batches.list_batches()
        ]
        self._fill(self._batches_table, rows)

    def _open_report(self):
        bid = self._selected_id(self._batches_table)
        if bid is None:
            return
        from ..reporting.batch_report import write_batch_report

        try:
            html_path, _ = write_batch_report(self._sf, bid, self._report_dir)
        except Exception as exc:
            self._status.setText(f"Report failed: {exc}")
            return
        self._status.setText(f"Report: {html_path}")
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(html_path))
        except Exception:
            pass

    # ---- Audit log ---------------------------------------------------------
    def _audit_tab(self):
        self._audit_table = self._table(["ID", "Time", "User", "Action", "Entity", "Signed"])
        verify = QPushButton("Verify chain")
        verify.clicked.connect(self._verify_chain)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_audit)
        return self._tab_widget(self._audit_table, [verify, refresh])

    def _refresh_audit(self):
        if self._audit_table is None:
            return  # this user has no audit.view tab
        with self._sf() as s:
            entries = AuditService(s).list_entries()
        rows = [
            (e["id"], e["ts"][:19], e["user"], e["action"], e["entity"], "✓" if e["signed"] else "")
            for e in entries
        ]
        self._fill(self._audit_table, rows)

    def _verify_chain(self):
        with self._sf() as s:
            ok, bad = AuditService(s).verify_chain()
        self._status.setText(
            "Audit chain VERIFIED — tamper-evident, intact." if ok
            else f"Audit chain BROKEN at entry {bad}!"
        )

    # ---- helpers -----------------------------------------------------------
    def _tab_widget(self, table, buttons):
        bar = QHBoxLayout()
        for b in buttons:
            bar.addWidget(b)
        bar.addStretch(1)
        layout = QVBoxLayout()
        layout.addWidget(table, 1)
        layout.addLayout(bar)
        w = QWidget()
        w.setLayout(layout)
        return w
