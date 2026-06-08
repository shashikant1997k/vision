from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
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
from .teach_model import (
    BATCH_FIELD,
    BATCH_FIELDS,
    INSPECTION_TYPES,
    ROTATIONS,
    TeachModel,
    build_config,
    modes_for,
    read_config,
    tool_config,
    value_hint,
)

_FRIENDLY = {d["key"]: d["label"] for d in INSPECTION_TYPES}


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
        reference_images: list | None = None,
        session_factory=None,
        product: str = "New Product",
        recipe_id: str = "recipe",
        reject_lanes: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Teach")
        self._user_id = user_id
        # bank of captured product images; teach on one, test across all
        self._bank = list(reference_images) if reference_images else [reference_image]
        self._reference_index = 0
        self._reference = self._bank[0]
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
        self._image.roiAdjusted.connect(self._on_roi_adjusted)
        self._guide = QLabel()
        self._guide.setWordWrap(True)
        self._guide.setStyleSheet("padding:6px; background:#eef; border:1px solid #99c")

        # filmstrip: step through captured images, pick the reference, test all
        self._img_label = QLabel()
        prev_btn = QPushButton("◀ Prev")
        prev_btn.clicked.connect(self._prev_image)
        next_btn = QPushButton("Next ▶")
        next_btn.clicked.connect(self._next_image)
        rotate_btn = QPushButton("Rotate image ⟳")
        rotate_btn.setToolTip("Rotate the whole image (for a sideways-mounted camera / photo).")
        rotate_btn.clicked.connect(self._rotate_image)
        zoom_in = QPushButton("➕")
        zoom_in.setFixedWidth(34)
        zoom_in.setToolTip("Zoom in (or scroll the mouse wheel over the image)")
        zoom_in.clicked.connect(lambda: self._image.zoom_by(1.25))
        zoom_out = QPushButton("➖")
        zoom_out.setFixedWidth(34)
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self._image.zoom_by(1 / 1.25))
        self._zoom_label = QLabel("100%")
        fit_btn = QPushButton("Fit")
        fit_btn.setToolTip("Reset zoom to fit")
        fit_btn.clicked.connect(self._image.reset_view)
        self._image.zoomChanged.connect(lambda z: self._zoom_label.setText(f"{int(z * 100)}%"))
        test_all_btn = QPushButton("Test all images")
        test_all_btn.clicked.connect(self._test_all)
        film = QHBoxLayout()
        film.addWidget(prev_btn)
        film.addWidget(self._img_label)
        film.addWidget(next_btn)
        film.addWidget(rotate_btn)
        film.addWidget(zoom_out)
        film.addWidget(self._zoom_label)
        film.addWidget(zoom_in)
        film.addWidget(fit_btn)
        film.addStretch(1)
        film.addWidget(test_all_btn)
        film_widget = QWidget()
        film_widget.setLayout(film)

        left = QVBoxLayout()
        left.addWidget(self._image, 1)
        left.addWidget(film_widget)
        left.addWidget(self._guide)
        left_widget = QWidget()
        left_widget.setLayout(left)

        # --- recipe name ---
        self._recipe_name = QLineEdit("" if self._model.product == "New Product" else self._model.product)
        self._recipe_name.setPlaceholderText("Recipe name, e.g. Tablets 500mg")
        self._recipe_name.textChanged.connect(self._name_edited)
        name_form = QFormLayout()
        name_form.addRow("Recipe name", self._recipe_name)

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
        self._locator_btn = QPushButton("Set part locator (follows the part)")
        self._locator_btn.setToolTip(
            "Draw a box around a distinctive, fixed feature (logo/edge/corner). "
            "Inspections then follow the part as it shifts on the line."
        )
        self._locator_btn.clicked.connect(self._arm_locator)
        palette_layout.addWidget(self._locator_btn)
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
        side.addLayout(name_form)
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
        self._update_img_label()
        self._refresh_view()

    # ---- captured-image bank (filmstrip) ----------------------------------
    def _update_img_label(self) -> None:
        self._img_label.setText(f"Image {self._reference_index + 1} / {len(self._bank)}")

    def _set_reference_index(self, index: int) -> None:
        if not self._bank:
            return
        self._reference_index = index % len(self._bank)
        self._reference = self._bank[self._reference_index]
        self._last_results = None
        self._image.reset_view()  # back to fit when switching images
        self._update_img_label()
        self._refresh_view()

    def _prev_image(self) -> None:
        self._set_reference_index(self._reference_index - 1)

    def _next_image(self) -> None:
        self._set_reference_index(self._reference_index + 1)

    def _test_all(self) -> None:
        """Run the recipe over every captured image — a statistical check before
        the recipe goes live."""
        total = passed = 0
        for image in self._bank:
            for r in self._model.test(image):
                total += 1
                passed += int(r.passed)
        self._status.setText(
            f"Tested {len(self._bank)} captured image(s): {passed}/{total} products passed"
        )

    # ---- property panels --------------------------------------------------
    def _build_product_props(self) -> QWidget:
        self._p_name = QLineEdit()
        self._p_name.textChanged.connect(self._product_edited)
        self._p_lane = QComboBox()
        self._p_lane.addItems(self._lanes)
        self._p_lane.currentTextChanged.connect(self._product_edited)
        self._p_logic = QComboBox()
        self._p_logic.addItem("All inspections pass", "all")
        self._p_logic.addItem("Any inspection passes", "any")
        self._p_logic.setToolTip("PASS rule over this product's required inspections.")
        self._p_logic.currentTextChanged.connect(self._product_edited)
        form = QFormLayout()
        form.addRow("Name", self._p_name)
        form.addRow("Reject lane", self._p_lane)
        form.addRow("Pass when", self._p_logic)
        w = QWidget()
        w.setLayout(form)
        w.hide()
        return w

    def _build_tool_props(self) -> QWidget:
        self._t_name = QLineEdit()
        self._t_name.textChanged.connect(self._tool_edited)
        self._t_type = QLabel("")
        self._t_mode = QComboBox()
        self._t_mode.setToolTip(
            "Fixed = the value never changes. Any readable / Pattern = variable "
            "(serial, date, etc.)."
        )
        self._t_mode.currentTextChanged.connect(self._tool_edited)
        self._t_value = QLineEdit()
        self._t_value.textChanged.connect(self._tool_edited)
        self._t_field = QComboBox()
        for key, label in BATCH_FIELDS:
            self._t_field.addItem(label, key)
        self._t_field.setToolTip("Which batch value (entered at batch start) this text must contain.")
        self._t_field.currentTextChanged.connect(self._tool_edited)
        self._t_rotation = QComboBox()
        for deg in ROTATIONS:
            self._t_rotation.addItem(f"{deg}°", deg)
        self._t_rotation.setToolTip("Rotate the box before reading (for sideways print).")
        self._t_rotation.currentTextChanged.connect(self._tool_edited)
        self._t_required = QCheckBox("Required (fails the product if this fails)")
        self._t_required.setChecked(True)
        self._t_required.setToolTip("Uncheck to make this inspection informational only.")
        self._t_required.stateChanged.connect(self._tool_edited)
        self._t_lastread = QLabel("")
        self._t_lastread.setWordWrap(True)
        self._t_lastread.setStyleSheet("color:#225; font-weight:bold")
        form = QFormLayout()
        form.addRow("Name", self._t_name)
        form.addRow("Type", self._t_type)
        form.addRow("Match", self._t_mode)
        form.addRow("Value", self._t_value)
        form.addRow("Batch field", self._t_field)
        form.addRow("Rotation", self._t_rotation)
        form.addRow("", self._t_required)
        form.addRow("Last read", self._t_lastread)
        w = QWidget()
        w.setLayout(form)
        w.hide()
        return w

    def _sync_tool_inputs(self, mode: str) -> None:
        self._t_value.setEnabled(mode != BATCH_FIELD)
        self._t_field.setEnabled(mode == BATCH_FIELD)

    # ---- palette / drawing ------------------------------------------------
    def _arm_tool(self, type_key: str) -> None:
        self._pending = ("tool", type_key)
        self._set_guide(f"Now drag a box around the {_FRIENDLY[type_key].split('(')[0].strip()} on the image.")

    def _arm_region(self) -> None:
        self._pending = ("region",)
        self._set_guide("Now drag a box around the product / area on the image.")

    def _arm_locator(self) -> None:
        self._pending = ("locator",)
        self._set_guide(
            "Draw a box around a <b>distinctive, always-present feature</b> "
            "(logo, edge, corner) — inspections will follow it as the part shifts."
        )

    def _on_roi_drawn(self, x: int, y: int, w: int, h: int) -> None:
        if self._pending is None:
            self._set_guide("Click <b>Read Code</b> or <b>Read Text</b> first, then drag a box.")
            return
        self._last_results = None
        if self._pending[0] == "locator":
            self._set_locator(x, y, w, h)
            return
        if self._pending[0] == "region":
            idx = self._model.add_region(
                f"Product {len(self._model.regions) + 1}", ROI(x, y, w, h), self._lanes[0]
            )
            self._selected = ("region", idx)
        else:
            type_key = self._pending[1]
            region_index = self._ensure_region()
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

    def _teach_image(self):
        from ..tools.transform import rotate_image

        return rotate_image(self._reference, self._model.image_rotation)

    def _rotate_image(self) -> None:
        self._model.image_rotation = (self._model.image_rotation + 90) % 360
        teach = self._teach_image()
        h, w = teach.shape[:2]
        if self._model.regions:
            self._model.regions[0].roi = ROI(0, 0, w, h)  # keep the default product full-frame
        self._last_results = None
        self._refresh_view()

    def _set_locator(self, x: int, y: int, w: int, h: int) -> None:
        from ..domain.entities import Fixture
        from ..runtime.locator import encode_template

        region_index = self._ensure_region()
        region = self._model.regions[region_index]
        try:
            template = encode_template(self._teach_image(), ROI(x, y, w, h))
        except Exception as exc:
            self._status.setText(f"Could not set locator: {exc}")
            self._pending = None
            return
        region.fixture = Fixture(template=template, anchor_x=x, anchor_y=y)
        self._selected = ("region", region_index)
        self._pending = None
        self._set_guide(
            "Part locator set ✓ — inspections now follow the part. "
            "Add inspections or click <b>Test</b>."
        )
        self._rebuild_tree()
        self._refresh_view()

    def _on_roi_adjusted(self, x: int, y: int, w: int, h: int) -> None:
        """A selected box's handles were dragged — update its ROI."""
        if self._selected is None:
            return
        if self._selected[0] == "region":
            self._model.regions[self._selected[1]].roi = ROI(x, y, w, h)
        else:
            region = self._model.regions[self._selected[1]]
            region.tools[self._selected[2]].roi = ROI(
                max(0, x - region.roi.x), max(0, y - region.roi.y), w, h
            )
        self._last_results = None
        self._refresh_view()

    def _ensure_region(self) -> int:
        """Return a valid product index, creating a default full-frame product
        if none exists (so drawing an inspection never crashes)."""
        if not self._model.regions:
            h, w = self._teach_image().shape[:2]
            return self._model.add_region("Product 1", ROI(0, 0, w, h), self._lanes[0])
        if self._selected is not None and self._selected[1] < len(self._model.regions):
            return self._selected[1]
        return len(self._model.regions) - 1

    # ---- tree -------------------------------------------------------------
    def _result_maps(self):
        """Build {region_id: passed} and {(region_id, tool_id): ToolResult} from
        the last Test (empty if not tested / edited since)."""
        region_pass: dict = {}
        tool_result: dict = {}
        for r in self._last_results or []:
            region_pass[r.region_id] = r.passed
            for tr in r.tool_results:
                tool_result[(r.region_id, tr.tool_id)] = tr
        return region_pass, tool_result

    def _last_read_for(self, region_id, tool_id) -> str:
        for rr in self._last_results or []:
            if rr.region_id == region_id:
                for tr in rr.tool_results:
                    if tr.tool_id == tool_id:
                        return _disp(tr.measured_value) or "(nothing read)"
        return ""

    def _rebuild_tree(self) -> None:
        green = QBrush(QColor(0, 140, 0))
        red = QBrush(QColor(200, 0, 0))
        region_pass, tool_result = self._result_maps()
        self._tree.blockSignals(True)
        self._tree.clear()
        for r, region in enumerate(self._model.regions):
            label = f"{region.name}  →  {region.reject_output}"
            if region.region_id in region_pass:
                label += "   " + ("✓ PASS" if region_pass[region.region_id] else "✗ REJECT")
            parent = QTreeWidgetItem([label])
            parent.setData(0, Qt.UserRole, ("region", r))
            if region.region_id in region_pass:
                parent.setForeground(0, green if region_pass[region.region_id] else red)
            for t, tool in enumerate(region.tools):
                friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
                tlabel = f"{tool.tool_id} · {friendly}"
                res = tool_result.get((region.region_id, tool.tool_id))
                if res is not None:
                    read = _disp(res.measured_value) or "(no read)"
                    tlabel += f"   {'✓' if res.passed else '✗'}  read “{read[:40]}”"
                child = QTreeWidgetItem([tlabel])
                child.setData(0, Qt.UserRole, ("tool", r, t))
                if res is not None:
                    child.setForeground(0, green if res.passed else red)
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
            logic_index = self._p_logic.findData(getattr(region, "pass_logic", "all"))
            self._p_logic.setCurrentIndex(logic_index if logic_index >= 0 else 0)
            self._product_props.show()
            self._tool_props.hide()
        else:
            region = self._model.regions[self._selected[1]]
            tool = region.tools[self._selected[2]]
            info = read_config(tool.tool_type, tool.config)
            self._t_name.setText(tool.tool_id)
            self._t_type.setText(_FRIENDLY.get(tool.tool_type, tool.tool_type))
            self._t_mode.clear()
            self._t_mode.addItems(modes_for(tool.tool_type))
            self._t_mode.setCurrentText(info["mode"])
            self._t_value.setText(info["value"])
            self._t_value.setPlaceholderText(value_hint(tool.tool_type, info["mode"]))
            rotation_index = self._t_rotation.findData(info["rotation"])
            self._t_rotation.setCurrentIndex(rotation_index if rotation_index >= 0 else 0)
            field_index = self._t_field.findData(info["field"])
            self._t_field.setCurrentIndex(field_index if field_index >= 0 else 0)
            self._t_required.setChecked(tool.config.get("required", True))
            self._t_lastread.setText(self._last_read_for(region.region_id, tool.tool_id))
            self._sync_tool_inputs(info["mode"])
            self._product_props.hide()
            self._tool_props.show()
        self._loading = False

    # ---- property edits ---------------------------------------------------
    def _name_edited(self) -> None:
        name = self._recipe_name.text().strip() or "New Recipe"
        self._model.product = name
        self._model.recipe_id = name

    def _product_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "region":
            return
        region = self._model.regions[self._selected[1]]
        region.name = self._p_name.text()
        region.reject_output = self._p_lane.currentText()
        region.pass_logic = self._p_logic.currentData() or "all"
        item = self._tree.currentItem()  # update label in place (no cursor reset)
        if item is not None:
            item.setText(0, f"{region.name}  →  {region.reject_output}")
        self._last_results = None
        self._refresh_view()

    def _tool_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "tool":
            return
        region = self._model.regions[self._selected[1]]
        tool = region.tools[self._selected[2]]
        tool.tool_id = self._t_name.text()
        mode = self._t_mode.currentText() or modes_for(tool.tool_type)[0]
        cfg = build_config(
            tool.tool_type,
            mode,
            self._t_value.text().strip(),
            rotation=self._t_rotation.currentData() or 0,
            field=self._t_field.currentData() or "",
        )
        if not self._t_required.isChecked():
            cfg["required"] = False
        tool.config = cfg
        self._t_value.setPlaceholderText(value_hint(tool.tool_type, mode))
        self._sync_tool_inputs(mode)
        item = self._tree.currentItem()
        if item is not None:
            friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
            item.setText(0, f"{tool.tool_id} · {friendly}")
        self._last_results = None
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
        base = self._teach_image()
        if self._last_results is not None:
            image = draw_overlay(base, self._model.to_recipe(), self._last_results)
            self._image.setImage(image)
            self._image.set_selected_roi(None)  # show results cleanly, no handles
        else:
            image = draw_layout(base, self._model.to_recipe())
            self._image.setImage(image)
            self._image.set_selected_roi(None if self._pending else self._selected_abs_roi())

    def _set_guide(self, text: str) -> None:
        self._guide.setText(text)

    # ---- actions ----------------------------------------------------------
    def _test(self) -> None:
        if not any(region.tools for region in self._model.regions):
            self._status.setText("Add at least one inspection (Read Code / Read Text) first.")
            return
        self._last_results = self._model.test(self._reference)
        self._rebuild_tree()  # annotate the inspection plan with ✓/✗ + read values
        self._refresh_view()
        self._status.setText(self._results_summary())

    def _results_summary(self) -> str:
        products = self._last_results or []
        n_pass = sum(1 for r in products if r.passed)
        verdict = "PASS" if products and n_pass == len(products) else "REJECT"
        lines = [f"Result: {verdict}   ({n_pass}/{len(products)} products passed)"]
        for r in products:
            for tr in r.tool_results:
                mark = "✓" if tr.passed else "✗"
                read = _disp(tr.measured_value) or "(nothing read)"
                detail = ""
                if not tr.passed:
                    info = tr.detail or {}
                    if info.get("reason") == "no_decode":
                        detail = " — code did not scan"
                    elif tr.expected_value:
                        detail = f" — expected {_disp(tr.expected_value)!r}"
                    else:
                        detail = " — not matched"
                lines.append(f"   {mark} {tr.tool_id}: read “{read}”{detail}")
        lines += self._locator_diagnostics()
        return "\n".join(lines)

    def _locator_diagnostics(self) -> list[str]:
        """Report, per product with a part locator, whether the locator found the
        feature on the current image and how strongly."""
        from ..runtime.locator import locate

        out = []
        teach = self._teach_image()
        for region in self._model.regions:
            fixture = getattr(region, "fixture", None)
            if fixture is None:
                continue
            dx, dy, score = locate(teach, fixture)
            if score >= fixture.min_score:
                out.append(f"   ⌖ {region.name} locator: found (score {score:.2f}, shift {dx:+d},{dy:+d}px)")
            else:
                out.append(
                    f"   ⌖ {region.name} locator: WEAK/NOT FOUND (score {score:.2f}) — "
                    "use a more distinctive feature"
                )
        return out

    def _validate(self) -> str | None:
        """Return a human message if the recipe isn't ready to save, else None."""
        if not self._recipe_name.text().strip():
            return "Enter a recipe name before saving."
        if not any(r.tools for r in self._model.regions):
            return "Add at least one inspection (Read Code / Read Text) before saving."
        for region in self._model.regions:
            for tool in region.tools:
                cfg = tool.config or {}
                if cfg.get("match") == "exact" and not (cfg.get("expected") or "").strip():
                    return f"Inspection '{tool.tool_id}' is Fixed value but its value is empty."
                if cfg.get("match") == "regex" and not (cfg.get("pattern") or "").strip():
                    return f"Inspection '{tool.tool_id}' is Matches pattern but no pattern is set."
                if cfg.get("expected_data") == "" and "pattern" not in cfg and cfg.get("gs1") and False:
                    pass  # code 'Any readable' is valid with empty value
        return None

    def _save(self) -> None:
        if self._sf is None:
            self._status.setText("No database configured — cannot save.")
            return
        problem = self._validate()
        if problem:
            self._status.setText("⚠ " + problem)
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


def _disp(value) -> str:
    """Readable string for display (control chars like the GS1 0x1d → <GS>)."""
    if value is None:
        return ""
    return str(value).replace("\x1d", "<GS>")
