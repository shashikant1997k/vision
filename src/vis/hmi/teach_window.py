from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..common.types import ROI
from ..runtime import draw_layout, draw_overlay
from .approve_dialog import ApproveDialog
from .roi_label import ImageRoiLabel
from .teach_model import INSPECTION_TYPES, TeachModel, expected_of, tool_config

_FRIENDLY = {d["key"]: d["label"] for d in INSPECTION_TYPES}
_EXPECTED_HINT = {d["key"]: d["expected_label"] for d in INSPECTION_TYPES}


class TeachWindow(QMainWindow):
    """Teach a recipe by direct manipulation: pick an inspection, draw its box on
    the image, edit it in the properties panel, test, save and approve.

    Modelled on the Cognex EasyBuilder / Keyence pattern: a palette of
    inspections, a tree of what you've added, and a properties panel for the
    selected item — instead of filling in coordinate forms.
    """

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
        self._saved_recipe_id: int | None = None
        self._lanes = reject_lanes or ["lane1", "lane2"]
        self._selected = None  # ("region", r) | ("tool", r, t) | None
        self._pending = None  # None | ("region",) | ("tool", type_key)
        self._last_results = None
        self._loading = False

        h, w = reference_image.shape[:2]
        # Start with one product covering the whole image (the common single-
        # product case) so the user can immediately draw an inspection.
        self._model.add_region("Product 1", ROI(0, 0, w, h), self._lanes[0])

        # --- image (drawable) ---
        self._image = ImageRoiLabel()
        self._image.roiSelected.connect(self._on_roi_drawn)
        self._guide = QLabel()
        self._guide.setWordWrap(True)
        self._guide.setStyleSheet("padding:6px; background:#eef; border:1px solid #99c")

        left = QVBoxLayout()
        left.addWidget(self._image, 1)
        left.addWidget(self._guide)
        left_widget = QWidget()
        left_widget.setLayout(left)

        # --- palette ---
        palette = QGroupBox("Add inspection")
        palette_layout = QVBoxLayout()
        for definition in INSPECTION_TYPES:
            btn = QPushButton(definition["label"])
            btn.clicked.connect(lambda _checked, k=definition["key"]: self._arm_tool(k))
            palette_layout.addWidget(btn)
        add_area = QPushButton("+ Add another product / area")
        add_area.clicked.connect(self._arm_region)
        palette_layout.addWidget(add_area)
        palette.setLayout(palette_layout)

        # --- inspection plan tree ---
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Inspection plan"])
        self._tree.itemSelectionChanged.connect(self._on_tree_selection)
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete_selected)

        # --- properties panel ---
        self._props_box = QGroupBox("Properties")
        self._product_props = self._build_product_props()
        self._tool_props = self._build_tool_props()
        props_layout = QVBoxLayout()
        props_layout.addWidget(self._product_props)
        props_layout.addWidget(self._tool_props)
        self._props_box.setLayout(props_layout)

        # --- actions ---
        self._status = QLabel("")
        self._status.setWordWrap(True)
        test_btn = QPushButton("Test")
        test_btn.clicked.connect(self._test)
        save_btn = QPushButton("Save draft")
        save_btn.clicked.connect(self._save)
        save_btn.setEnabled(session_factory is not None)
        self._approve_btn = QPushButton("Approve…")
        self._approve_btn.clicked.connect(self._approve)
        self._approve_btn.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(test_btn)
        actions.addWidget(save_btn)
        actions.addWidget(self._approve_btn)

        side = QVBoxLayout()
        side.addWidget(palette)
        side.addWidget(self._tree, 1)
        side.addWidget(delete_btn)
        side.addWidget(self._props_box)
        side.addLayout(actions)
        side.addWidget(self._status)
        side_widget = QWidget()
        side_widget.setLayout(side)

        root = QHBoxLayout()
        root.addWidget(left_widget, 3)
        root.addWidget(side_widget, 2)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self._rebuild_tree()
        self._set_guide("Click <b>Read Code</b> or <b>Read Text</b>, then drag a box on the image.")
        self._refresh_view()

    # ---- property panels --------------------------------------------------
    def _build_product_props(self) -> QWidget:
        self._p_name = QLineEdit()
        self._p_name.textChanged.connect(self._product_edited)
        self._p_lane = QComboBox()
        self._p_lane.addItems(self._lanes)
        self._p_lane.currentTextChanged.connect(self._product_edited)
        form = QFormLayout()
        form.addRow("Name", self._p_name)
        form.addRow("Reject lane", self._p_lane)
        w = QWidget()
        w.setLayout(form)
        w.hide()
        return w

    def _build_tool_props(self) -> QWidget:
        self._t_name = QLineEdit()
        self._t_name.textChanged.connect(self._tool_edited)
        self._t_type = QLabel("")
        self._t_expected = QLineEdit()
        self._t_expected.textChanged.connect(self._tool_edited)
        form = QFormLayout()
        form.addRow("Name", self._t_name)
        form.addRow("Type", self._t_type)
        form.addRow("Expected", self._t_expected)
        w = QWidget()
        w.setLayout(form)
        w.hide()
        return w

    # ---- palette / drawing ------------------------------------------------
    def _arm_tool(self, type_key: str) -> None:
        self._pending = ("tool", type_key)
        self._set_guide(f"Now drag a box around the {_FRIENDLY[type_key].split('(')[0].strip()} on the image.")

    def _arm_region(self) -> None:
        self._pending = ("region",)
        self._set_guide("Now drag a box around the product / area on the image.")

    def _on_roi_drawn(self, x: int, y: int, w: int, h: int) -> None:
        if self._pending is None:
            self._set_guide("Click <b>Read Code</b> or <b>Read Text</b> first, then drag a box.")
            return
        self._last_results = None
        if self._pending[0] == "region":
            idx = self._model.add_region(
                f"Product {len(self._model.regions) + 1}", ROI(x, y, w, h), self._lanes[0]
            )
            self._selected = ("region", idx)
        else:
            type_key = self._pending[1]
            region_index = self._current_region_index()
            region = self._model.regions[region_index]
            rel = ROI(max(0, x - region.roi.x), max(0, y - region.roi.y), w, h)
            count = sum(len(r.tools) for r in self._model.regions) + 1
            tool_id = ("code" if type_key == "code_verify" else "text") + str(count)
            t_idx = self._model.add_tool(
                region_index, tool_id, type_key, rel, tool_config(type_key, "")
            )
            self._selected = ("tool", region_index, t_idx)
            self._set_guide(
                "Added. Set the <b>Expected</b> value below (or leave blank), "
                "then add more or click <b>Test</b>."
            )
        self._pending = None
        self._rebuild_tree()
        self._refresh_view()

    def _current_region_index(self) -> int:
        if self._selected is not None:
            return self._selected[1]
        return 0

    # ---- tree -------------------------------------------------------------
    def _rebuild_tree(self) -> None:
        self._tree.blockSignals(True)
        self._tree.clear()
        for r, region in enumerate(self._model.regions):
            parent = QTreeWidgetItem([f"{region.name}  →  {region.reject_output}"])
            parent.setData(0, Qt.UserRole, ("region", r))
            for t, tool in enumerate(region.tools):
                friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
                child = QTreeWidgetItem([f"{tool.tool_id} · {friendly}"])
                child.setData(0, Qt.UserRole, ("tool", r, t))
                parent.addChild(child)
            self._tree.addTopLevelItem(parent)
        self._tree.expandAll()
        self._select_in_tree(self._selected)
        self._tree.blockSignals(False)
        self._load_properties()

    def _select_in_tree(self, role) -> None:
        if role is None:
            return
        for item in self._iter_items():
            if item.data(0, Qt.UserRole) == role:
                self._tree.setCurrentItem(item)
                return

    def _iter_items(self):
        items = []
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            items.append(top)
            for j in range(top.childCount()):
                items.append(top.child(j))
        return items

    def _on_tree_selection(self) -> None:
        current = self._tree.currentItem()
        self._selected = current.data(0, Qt.UserRole) if current is not None else None
        self._load_properties()
        self._refresh_view()

    def _load_properties(self) -> None:
        self._loading = True
        if self._selected is None:
            self._product_props.hide()
            self._tool_props.hide()
        elif self._selected[0] == "region":
            region = self._model.regions[self._selected[1]]
            self._p_name.setText(region.name)
            self._p_lane.setCurrentText(region.reject_output)
            self._product_props.show()
            self._tool_props.hide()
        else:
            region = self._model.regions[self._selected[1]]
            tool = region.tools[self._selected[2]]
            self._t_name.setText(tool.tool_id)
            self._t_type.setText(_FRIENDLY.get(tool.tool_type, tool.tool_type))
            self._t_expected.setPlaceholderText(_EXPECTED_HINT.get(tool.tool_type, ""))
            self._t_expected.setText(expected_of(tool.tool_type, tool.config))
            self._product_props.hide()
            self._tool_props.show()
        self._loading = False

    # ---- property edits ---------------------------------------------------
    def _product_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "region":
            return
        region = self._model.regions[self._selected[1]]
        region.name = self._p_name.text()
        region.reject_output = self._p_lane.currentText()
        self._last_results = None
        self._rebuild_tree()
        self._refresh_view()

    def _tool_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "tool":
            return
        region = self._model.regions[self._selected[1]]
        tool = region.tools[self._selected[2]]
        tool.tool_id = self._t_name.text()
        tool.config = tool_config(tool.tool_type, self._t_expected.text().strip())
        self._last_results = None
        self._rebuild_tree()
        self._refresh_view()

    def _delete_selected(self) -> None:
        if self._selected is None:
            return
        if self._selected[0] == "region":
            self._model.remove_region(self._selected[1])
        else:
            self._model.remove_tool(self._selected[1], self._selected[2])
        self._selected = None
        self._last_results = None
        self._rebuild_tree()
        self._refresh_view()

    # ---- view -------------------------------------------------------------
    def _selected_abs_roi(self):
        if self._selected is None:
            return None
        if self._selected[0] == "region":
            r = self._model.regions[self._selected[1]].roi
            return (r.x, r.y, r.w, r.h)
        region = self._model.regions[self._selected[1]]
        t = region.tools[self._selected[2]].roi
        return (region.roi.x + t.x, region.roi.y + t.y, t.w, t.h)

    def _refresh_view(self) -> None:
        if self._last_results is not None:
            image = draw_overlay(self._reference, self._model.to_recipe(), self._last_results)
        else:
            image = draw_layout(
                self._reference, self._model.to_recipe(), highlight=self._selected_abs_roi()
            )
        self._image.setImage(image)

    def _set_guide(self, text: str) -> None:
        self._guide.setText(text)

    # ---- actions ----------------------------------------------------------
    def _test(self) -> None:
        self._last_results = self._model.test(self._reference)
        self._refresh_view()
        passed = sum(1 for r in self._last_results if r.passed)
        self._status.setText(f"Test: {passed}/{len(self._last_results)} products passed")

    def _save(self) -> None:
        if self._sf is None:
            self._status.setText("No database configured — cannot save.")
            return
        from ..db.store import RecipeRepository

        try:
            recipe_id = RecipeRepository(self._sf).save_draft(
                self._model.to_recipe(), user_id=self._user_id
            )
        except Exception as exc:
            self._status.setText(f"Save failed: {exc}")
            return
        self._saved_recipe_id = recipe_id
        self._approve_btn.setEnabled(True)
        self._status.setText(f"Saved draft recipe #{recipe_id}")

    def _approve(self) -> None:
        if self._saved_recipe_id is None:
            self._status.setText("Save the draft first.")
            return
        if self._sf is None:
            self._status.setText("No database configured — cannot approve.")
            return
        dialog = ApproveDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        from ..db.store import RecipeRepository

        try:
            RecipeRepository(self._sf).approve(
                self._saved_recipe_id, self._user_id, dialog.password_value, dialog.meaning_value
            )
        except Exception as exc:
            self._status.setText(f"Approve failed: {exc}")
            return
        self._status.setText(f"Recipe #{self._saved_recipe_id} approved")
        self._approve_btn.setEnabled(False)
