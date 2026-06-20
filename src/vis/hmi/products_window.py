"""Products screen: the catalogue of products and each product's inspection job.

A product runs on the line only once it has an APPROVED job (recipe). From here
you create products and teach/edit their job; teaching opens the live Teach
screen bound to the product, via the teach_cb(code, name, recipe_id) callback.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.products import ProductRepository


class ProductsWindow(QMainWindow):
    def __init__(self, session_factory, user_id, teach_cb, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Products")
        self._uid = user_id
        self._repo = ProductRepository(session_factory)
        self._teach_cb = teach_cb
        self._products: list[dict] = []

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Code", "Name", "Job versions", "Approved", "Status"]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.doubleClicked.connect(lambda *_: self._edit_job())

        new_btn = QPushButton("New product…")
        new_btn.clicked.connect(self._new_product)
        rename_btn = QPushButton("Rename…")
        rename_btn.clicked.connect(self._rename_product)
        teach_btn = QPushButton("Teach new job…")
        teach_btn.setProperty("variant", "primary")
        teach_btn.clicked.connect(self._teach_new)
        edit_btn = QPushButton("Edit job…")
        edit_btn.clicked.connect(self._edit_job)
        refresh = QPushButton("↻")
        refresh.setFixedWidth(38)
        refresh.clicked.connect(self._refresh)

        bar = QHBoxLayout()
        bar.addWidget(new_btn)
        bar.addWidget(rename_btn)
        bar.addStretch(1)
        bar.addWidget(teach_btn)
        bar.addWidget(edit_btn)
        bar.addWidget(refresh)

        self._status = QLabel("")
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        hint = QLabel("Each product runs on the line only once it has an approved job.")
        hint.setStyleSheet("color:#667")
        root.addWidget(hint)
        root.addLayout(bar)
        root.addWidget(self._table, 1)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._refresh()

    def _refresh(self) -> None:
        self._products = self._repo.list_products()
        self._table.setRowCount(len(self._products))
        for r, p in enumerate(self._products):
            if p["approved"]:
                status, colour = "● ready", QColor(0, 140, 0)
            elif p["recipes"]:
                status, colour = "draft (not approved)", QColor(184, 134, 11)
            else:
                status, colour = "no job — teach one", QColor(200, 0, 0)
            for c, v in enumerate((p["code"], p["name"], str(p["recipes"]),
                                   str(p["approved"]), status)):
                item = QTableWidgetItem(v)
                if c == 4:
                    item.setForeground(colour)
                self._table.setItem(r, c, item)

    def _selected(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._products):
            self._status.setText("Select a product first.")
            return None
        return self._products[row]

    def _new_product(self) -> None:
        code, ok = QInputDialog.getText(self, "New product", "Product code (unique):")
        if not ok or not code.strip():
            return
        name, ok = QInputDialog.getText(self, "New product", "Product name:", text=code.strip())
        if not ok:
            return
        try:
            self._repo.create_product(self._uid, code.strip(), name.strip() or code.strip())
        except Exception as exc:
            self._status.setText(f"Could not create: {exc}")
            return
        self._refresh()
        self._status.setText(f"Product {code.strip()} created — select it and Teach new job.")

    def _rename_product(self) -> None:
        p = self._selected()
        if p is None:
            return
        name, ok = QInputDialog.getText(self, "Rename product", "Product name:", text=p["name"])
        if not ok or not name.strip():
            return
        try:
            self._repo.update_product(self._uid, p["id"], name.strip())
        except Exception as exc:
            self._status.setText(f"Could not rename: {exc}")
            return
        self._refresh()

    def _teach_new(self) -> None:
        p = self._selected()
        if p is not None:
            self._teach_cb(p["code"], p["name"], None)

    def _edit_job(self) -> None:
        p = self._selected()
        if p is None:
            return
        rid = self._repo.latest_recipe(p["id"])
        if rid is None:
            self._status.setText("No job yet — click 'Teach new job'.")
            return
        self._teach_cb(p["code"], p["name"], rid)
