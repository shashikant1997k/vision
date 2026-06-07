from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..common.types import ROI
from ..runtime import draw_layout, draw_overlay
from .image import numpy_to_qpixmap
from .teach_model import TeachModel, tool_config

TOOL_TYPES = ["code_verify", "ocv_text"]


def _roi_form(max_w: int, max_h: int):
    x, y, w, h = (QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox())
    for sb, hi in ((x, max_w), (y, max_h), (w, max_w), (h, max_h)):
        sb.setMaximum(hi)
    w.setValue(min(200, max_w))
    h.setValue(min(80, max_h))
    return x, y, w, h


class TeachWindow(QMainWindow):
    """Define regions/tools on a reference image, test, and save a draft recipe."""

    def __init__(
        self,
        *,
        user_id,
        reference_image: np.ndarray,
        session_factory=None,
        product: str = "New Product",
        recipe_id: str = "recipe",
        reject_lanes: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Teach")
        self._user_id = user_id
        self._reference = reference_image
        self._sf = session_factory
        self._model = TeachModel(product, recipe_id)
        h, w = reference_image.shape[:2]
        lanes = reject_lanes or ["lane1", "lane2"]

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(560, 380)
        self._image.setStyleSheet("background:#111")

        # region form
        self._region_name = QLineEdit("Product 1")
        self._rx, self._ry, self._rw, self._rh = _roi_form(w, h)
        self._rw.setValue(min(w, w)); self._rh.setValue(min(h, h))
        self._lane = QComboBox(); self._lane.addItems(lanes)
        add_region = QPushButton("Add region"); add_region.clicked.connect(self._add_region)
        region_form = QFormLayout()
        region_form.addRow("Name", self._region_name)
        region_form.addRow("ROI x/y", _row(self._rx, self._ry))
        region_form.addRow("ROI w/h", _row(self._rw, self._rh))
        region_form.addRow("Reject lane", self._lane)
        region_form.addRow(add_region)
        region_box = QGroupBox("Region"); region_box.setLayout(region_form)

        # tool form
        self._region_select = QComboBox()
        self._tool_id = QLineEdit("code1")
        self._tool_type = QComboBox(); self._tool_type.addItems(TOOL_TYPES)
        self._tx, self._ty, self._tw, self._th = _roi_form(w, h)
        self._expected = QLineEdit()
        add_tool = QPushButton("Add tool"); add_tool.clicked.connect(self._add_tool)
        tool_form = QFormLayout()
        tool_form.addRow("Region", self._region_select)
        tool_form.addRow("Tool id", self._tool_id)
        tool_form.addRow("Type", self._tool_type)
        tool_form.addRow("ROI x/y", _row(self._tx, self._ty))
        tool_form.addRow("ROI w/h", _row(self._tw, self._th))
        tool_form.addRow("Expected", self._expected)
        tool_form.addRow(add_tool)
        tool_box = QGroupBox("Tool"); tool_box.setLayout(tool_form)

        self._status = QLabel("Add regions and tools, then Test and Save.")
        test_btn = QPushButton("Test"); test_btn.clicked.connect(self._test)
        save_btn = QPushButton("Save draft"); save_btn.clicked.connect(self._save)
        save_btn.setEnabled(session_factory is not None)
        actions = QHBoxLayout(); actions.addWidget(test_btn); actions.addWidget(save_btn)

        side = QVBoxLayout()
        side.addWidget(region_box)
        side.addWidget(tool_box)
        side.addLayout(actions)
        side.addWidget(self._status)
        side.addStretch(1)
        side_widget = QWidget(); side_widget.setLayout(side)

        root = QHBoxLayout()
        root.addWidget(self._image, 3)
        root.addWidget(side_widget, 2)
        central = QWidget(); central.setLayout(root)
        self.setCentralWidget(central)
        self._refresh_preview()

    def _add_region(self) -> None:
        idx = self._model.add_region(
            self._region_name.text().strip() or f"Product {len(self._model.regions) + 1}",
            ROI(self._rx.value(), self._ry.value(), self._rw.value(), self._rh.value()),
            self._lane.currentText(),
        )
        self._region_select.addItem(self._model.regions[idx].name, idx)
        self._status.setText(f"Added region {self._model.regions[idx].name}")
        self._refresh_preview()

    def _add_tool(self) -> None:
        if self._region_select.count() == 0:
            self._status.setText("Add a region first.")
            return
        region_index = self._region_select.currentData()
        ttype = self._tool_type.currentText()
        self._model.add_tool(
            region_index,
            self._tool_id.text().strip() or "tool",
            ttype,
            ROI(self._tx.value(), self._ty.value(), self._tw.value(), self._th.value()),
            tool_config(ttype, self._expected.text().strip()),
        )
        self._status.setText(f"Added tool {self._tool_id.text().strip()} ({ttype})")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        annotated = draw_layout(self._reference, self._model.to_recipe())
        self._set_image(annotated)

    def _test(self) -> None:
        results = self._model.test(self._reference)
        annotated = draw_overlay(self._reference, self._model.to_recipe(), results)
        self._set_image(annotated)
        passed = sum(1 for r in results if r.passed)
        self._status.setText(f"Test: {passed}/{len(results)} regions passed")

    def _save(self) -> None:
        if self._sf is None:
            self._status.setText("No database configured — cannot save.")
            return
        from ..db.store import RecipeRepository

        try:
            recipe_id = RecipeRepository(self._sf).save_draft(
                self._model.to_recipe(), user_id=self._user_id
            )
        except Exception as exc:  # surface permission / db errors to the operator
            self._status.setText(f"Save failed: {exc}")
            return
        self._status.setText(f"Saved draft recipe #{recipe_id}")

    def _set_image(self, array) -> None:
        pixmap = numpy_to_qpixmap(array)
        self._image.setPixmap(
            pixmap.scaled(self._image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


def _row(a, b) -> QWidget:
    box = QHBoxLayout(); box.addWidget(a); box.addWidget(b)
    w = QWidget(); w.setLayout(box)
    return w
