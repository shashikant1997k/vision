"""Batch orders screen: create a batch by selecting a product, then run it.

A supervisor creates the batch order ahead of the run (product + batch no +
MFG/EXP/MRP). The product's current approved job is bound to the batch. Open
batches then appear in the run selector on the live screen.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.batches import BatchService
from ..db.products import ProductRepository


class NewBatchDialog(QDialog):
    def __init__(self, products: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New batch order")
        self._product = QComboBox()
        for p in products:  # only products that have an approved job
            self._product.addItem(f"{p['code']} · {p['name']}", p["id"])
        self._batch_no = QLineEdit()
        self._batch_no.setPlaceholderText("e.g. B24-0613")
        self._lot = QLineEdit()
        self._mfg = QLineEdit()
        self._mfg.setPlaceholderText("MFG, e.g. 10/2025")
        self._exp = QLineEdit()
        self._exp.setPlaceholderText("EXP, e.g. 10/2027")
        self._mrp = QLineEdit()
        self._mrp.setPlaceholderText("MRP, e.g. 125.00")
        form = QFormLayout()
        form.addRow("Product", self._product)
        form.addRow("Batch no.", self._batch_no)
        form.addRow("Lot", self._lot)
        form.addRow("MFG", self._mfg)
        form.addRow("EXP", self._exp)
        form.addRow("MRP", self._mrp)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout()
        root.addLayout(form)
        root.addWidget(buttons)
        self.setLayout(root)

    def product_id(self):
        return self._product.currentData()

    def values(self) -> dict:
        return {
            "batch_no": self._batch_no.text().strip(),
            "lot": self._lot.text().strip(),
            "mfg": self._mfg.text().strip(),
            "expiry": self._exp.text().strip(),
            "mrp": self._mrp.text().strip(),
        }


class BatchOrdersWindow(QMainWindow):
    def __init__(self, session_factory, user_id, on_changed=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Batches")
        self._uid = user_id
        self._batches = BatchService(session_factory)
        self._products = ProductRepository(session_factory)
        self._on_changed = on_changed

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Batch no.", "Product", "Status", "Total", "Pass", "Started"]
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        new_btn = QPushButton("New batch order…")
        new_btn.setProperty("variant", "primary")
        new_btn.clicked.connect(self._new_batch)
        refresh = QPushButton("↻")
        refresh.setFixedWidth(38)
        refresh.clicked.connect(self._refresh)
        bar = QHBoxLayout()
        bar.addWidget(new_btn)
        bar.addStretch(1)
        bar.addWidget(refresh)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root = QVBoxLayout()
        hint = QLabel("Create a batch order, then run it from the live screen's batch selector.")
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
        rows = self._batches.list_batches()
        self._table.setRowCount(len(rows))
        for r, b in enumerate(rows):
            cells = (b["batch_no"], b["product"], b["status"],
                     str(b["total"]), str(b["passed"]), (b["started_at"] or "")[:19])
            for c, v in enumerate(cells):
                item = QTableWidgetItem(str(v))
                if c == 2:
                    item.setForeground(QColor(0, 140, 0) if b["status"] == "open"
                                       else QColor(120, 120, 120))
                self._table.setItem(r, c, item)

    def _new_batch(self) -> None:
        products = [p for p in self._products.list_products() if p["approved"]]
        if not products:
            self._status.setText(
                "No product has an approved job yet — teach + approve one in Products first."
            )
            return
        dialog = NewBatchDialog(products, self)
        if dialog.exec() != QDialog.Accepted:
            return
        vals = dialog.values()
        if not vals["batch_no"]:
            self._status.setText("Enter a batch number.")
            return
        recipe_id = self._products.latest_approved_recipe(dialog.product_id())
        if recipe_id is None:
            self._status.setText("That product has no approved job.")
            return
        variable = {k: v for k, v in vals.items() if k != "batch_no" and v}
        try:
            self._batches.start(
                recipe_id, vals["batch_no"], self._uid,
                mfg_date=vals["mfg"] or None, exp_date=vals["expiry"] or None,
                mrp=vals["mrp"] or None, variable_data=variable,
            )
        except Exception as exc:
            self._status.setText(f"Could not create batch: {exc}")
            return
        self._refresh()
        if self._on_changed is not None:
            self._on_changed()
        self._status.setText(f"Batch {vals['batch_no']} created — ready to run.")
