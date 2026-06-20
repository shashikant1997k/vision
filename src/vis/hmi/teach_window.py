from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
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
    QScrollArea,
    QSpinBox,
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
    BATCH_FIELDS,
    FONT_KEYS,
    INSPECTION_TYPES,
    MATCH_TOOLS,
    ROTATIONS,
    TeachModel,
    build_config,
    default_config,
    modes_for,
    read_config,
    tool_config,
    value_hint,
)

_FRIENDLY = {d["key"]: d["label"] for d in INSPECTION_TYPES}


class _TestWorker(QThread):
    """Run a blocking inspection callable off the GUI thread so Test / Test all
    can't freeze the UI (OCR inference + first-run model load take seconds).
    Results come back via a signal, which Qt delivers on the main thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # never let a worker crash take down the window
            self.failed.emit(str(exc))

_PALETTE_ICONS = {
    "code_verify": "▦",
    "ocv_text": "≣",
    "ocv_font": "▥",
    "presence": "●",
    "measure": "↔",
    "color_check": "◑",
    "template_match": "▣",
}


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
        image_provider=None,
        on_close=None,
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
        self._worker = None  # background Test/Test-all thread, when running
        self._pending_done = None
        # live-camera teaching: stream frames, Snap to freeze a reference to mark up
        self._image_provider = image_provider
        self._on_close = on_close
        self._live_frame = None
        self._live = False
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(120)
        self._live_timer.timeout.connect(self._live_tick)

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
        rotate_btn = QPushButton("Rotate ⟳")
        rotate_btn.setToolTip("Rotate the whole image (for a sideways-mounted camera / photo).")
        rotate_btn.clicked.connect(self._rotate_image)
        zoom_in = QPushButton("＋")
        zoom_in.setFixedWidth(36)
        zoom_in.setStyleSheet("padding: 6px 2px")
        zoom_in.setToolTip("Zoom in (or scroll the mouse wheel over the image)")
        zoom_in.clicked.connect(lambda: self._image.zoom_by(1.25))
        zoom_out = QPushButton("－")
        zoom_out.setFixedWidth(36)
        zoom_out.setStyleSheet("padding: 6px 2px")
        zoom_out.setToolTip("Zoom out")
        zoom_out.clicked.connect(lambda: self._image.zoom_by(1 / 1.25))
        self._zoom_label = QLabel("100%")
        fit_btn = QPushButton("Fit")
        fit_btn.setToolTip("Reset zoom to fit")
        fit_btn.clicked.connect(self._image.reset_view)
        self._image.zoomChanged.connect(lambda z: self._zoom_label.setText(f"{int(z * 100)}%"))
        self._test_all_btn = test_all_btn = QPushButton("Test all")
        test_all_btn.setToolTip("Run the recipe over all captured/loaded images.")
        test_all_btn.clicked.connect(self._test_all)
        self._live_btn = QPushButton("● Live")
        self._live_btn.setToolTip("Resume the live camera to reposition the product.")
        self._live_btn.clicked.connect(self._go_live)
        self._snap_btn = QPushButton("◉ Snap")
        self._snap_btn.setProperty("variant", "primary")
        self._snap_btn.setToolTip("Freeze the current live frame to draw inspection boxes on.")
        self._snap_btn.clicked.connect(self._snap)
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
        film.addWidget(self._live_btn)
        film.addWidget(self._snap_btn)
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

        # --- palette (grouped: Read | Measure & check | Layout) ---
        palette = QGroupBox("Add inspection")
        palette_layout = QVBoxLayout()
        palette_layout.setSpacing(3)

        def _section(title):
            lbl = QLabel(title)
            lbl.setStyleSheet("color:#667; font-weight:bold; margin-top:4px")
            palette_layout.addWidget(lbl)

        def _palette_btn(label, key, tip=""):
            btn = QPushButton(f"{_PALETTE_ICONS.get(key, '•')}  {label}")
            btn.setStyleSheet("text-align:left; padding:5px 8px")
            if tip:
                btn.setToolTip(tip)
            btn.clicked.connect(lambda _checked, k=key: self._arm_tool(k))
            palette_layout.addWidget(btn)

        _section("Read")
        for d in INSPECTION_TYPES:
            if d.get("category") == "read":
                _palette_btn(d["label"], d["key"])
        _section("Measure & check")
        for d in INSPECTION_TYPES:
            if d.get("category") == "inspect":
                _palette_btn(d["label"], d["key"])

        _section("Layout")
        add_area = QPushButton("＋  Add another product / area")
        add_area.setStyleSheet("text-align:left; padding:5px 8px")
        add_area.clicked.connect(self._arm_region)
        palette_layout.addWidget(add_area)
        self._locator_btn = QPushButton("⌖  Set part locator (follows the part)")
        self._locator_btn.setStyleSheet("text-align:left; padding:5px 8px")
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
        dup_btn = QPushButton("Duplicate")
        dup_btn.setToolTip("Copy the selected inspection (offset) — fast multi-field setup.")
        dup_btn.clicked.connect(self._duplicate_selected)
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete_selected)
        tree_buttons = QHBoxLayout()
        tree_buttons.addWidget(dup_btn)
        tree_buttons.addWidget(delete_btn)

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
        self._test_btn = test_btn = QPushButton("Test")
        test_btn.setProperty("variant", "primary")
        test_btn.clicked.connect(self._test)
        save_btn = QPushButton("Save draft")
        save_btn.clicked.connect(self._save)
        save_btn.setEnabled(session_factory is not None)
        self._approve_btn = QPushButton("Approve…")
        self._approve_btn.setProperty("variant", "primary")
        self._approve_btn.clicked.connect(self._approve)
        self._approve_btn.setEnabled(False)
        export_btn = QPushButton("Export…")
        export_btn.setToolTip("Export this recipe to a JSON file (move it to another station).")
        export_btn.clicked.connect(self._export)
        actions = QHBoxLayout()
        actions.addWidget(test_btn)
        actions.addWidget(save_btn)
        actions.addWidget(export_btn)
        actions.addWidget(self._approve_btn)

        side = QVBoxLayout()
        side.addLayout(name_form)
        side.addWidget(palette)
        side.addWidget(self._tree)
        side.addLayout(tree_buttons)
        side.addWidget(self._props_box)
        side.addLayout(actions)
        side.addWidget(self._status)
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setLayout(side)
        # bound the panel width and let it scroll, so long read values can never
        # push the window off-screen
        side_scroll = QScrollArea()
        side_scroll.setWidget(side_widget)
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setMinimumWidth(340)
        side_scroll.setMaximumWidth(760)  # user-resizable via the splitter

        # resizable split: drag the divider to give the image or the panel more
        # room (e.g. to reveal truncated read values)
        from PySide6.QtWidgets import QSplitter

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(side_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([760, 420])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        # long read values must wrap/clip, never widen the panel
        self._status.setMaximumWidth(430)
        self._t_lastread.setMaximumWidth(320)

        self._rebuild_tree()
        self._set_guide("Click <b>Read Code</b> or <b>Read Text</b>, then drag a box on the image.")
        self._update_img_label()
        self._refresh_view()
        if self._image_provider is not None:
            self._go_live()  # start in live mode: position the product, then Snap
        else:
            self._live_btn.hide()
            self._snap_btn.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self._pending is not None:
                self._pending = None
                self._set_guide("Cancelled. Pick an inspection from the palette to add another.")
            else:
                self._selected = None
                self._refresh_view()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        w = min(self.width(), avail.width() - 40)
        h = min(self.height(), avail.height() - 40)
        if w != self.width() or h != self.height():
            self.resize(w, h)
        self.move(
            max(avail.left() + 10, min(self.x(), avail.right() - w - 10)),
            max(avail.top() + 10, min(self.y(), avail.bottom() - h - 10)),
        )

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
        the recipe goes live. Runs off the GUI thread (OCR is slow)."""
        if not any(region.tools for region in self._model.regions):
            self._status.setText("Add at least one inspection (Read Code / Read Text) first.")
            return
        bank = list(self._bank)
        model = self._model

        def work():
            total = passed = 0
            for image in bank:
                for r in model.test(image):
                    total += 1
                    passed += int(r.passed)
            return (len(bank), passed, total)

        self._run_async(work, self._test_all_done,
                        "Testing all captured images… (running the recipe over each)")

    def _test_all_done(self, res) -> None:
        n, passed, total = res
        self._status.setText(f"Tested {n} captured image(s): {passed}/{total} products passed")

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
        self._p_locator = QLabel("none")
        clear_loc = QPushButton("Clear")
        clear_loc.setFixedWidth(60)
        clear_loc.clicked.connect(self._clear_locator)
        loc_row = QHBoxLayout()
        loc_row.addWidget(self._p_locator, 1)
        loc_row.addWidget(clear_loc)
        form = QFormLayout()
        form.addRow("Name", self._p_name)
        form.addRow("Reject lane", self._p_lane)
        form.addRow("Pass when", self._p_logic)
        form.addRow("Part locator", loc_row)
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
        self._t_search_x = QSpinBox()
        self._t_search_x.setRange(0, 300)
        self._t_search_x.setSuffix(" px")
        self._t_search_x.setToolTip(
            "Outer SEARCH region, horizontal: how far LEFT/RIGHT the print may "
            "drift from the drawn box. The tool locates the line inside, then reads."
        )
        self._t_search_x.valueChanged.connect(self._tool_edited)
        self._t_search_y = QSpinBox()
        self._t_search_y.setRange(0, 300)
        self._t_search_y.setSuffix(" px")
        self._t_search_y.setToolTip(
            "Outer SEARCH region, vertical: how far UP/DOWN the print may drift "
            "from the drawn box."
        )
        self._t_search_y.valueChanged.connect(self._tool_edited)
        self._t_minconf = QSpinBox()
        self._t_minconf.setRange(0, 100)
        self._t_minconf.setSuffix(" %")
        self._t_minconf.setToolTip("Reject if the read confidence is below this (0 = off).")
        self._t_minconf.valueChanged.connect(self._tool_edited)
        self._t_reader = QComboBox()
        self._t_reader.setToolTip("Reading engine — a licensed OCR/OCV library appears here once installed.")
        self._t_reader.currentTextChanged.connect(self._tool_edited)
        self._t_charset = QComboBox()
        for label, key in (("Any character", ""), ("Digits only", "digits"),
                           ("Letters only", "letters"), ("Letters + digits", "alnum")):
            self._t_charset.addItem(label, key)
        self._t_charset.setToolTip(
            "Restrict which characters this field can contain (digits-only dates "
            "kill 0/O, 5/S confusion) — documented vendor practice."
        )
        self._t_charset.currentIndexChanged.connect(self._tool_edited)
        self._t_font = QComboBox()
        self._t_font.setToolTip(
            "Trained OCV font (print technology + size). Train more in Fonts…"
        )
        self._t_font.currentIndexChanged.connect(self._font_changed)
        self._t_required = QCheckBox("Required (fails the product if this fails)")
        self._t_required.setChecked(True)
        self._t_required.setToolTip("Uncheck to make this inspection informational only.")
        self._t_required.toggled.connect(self._tool_edited)
        self._t_lastread = QLabel("")
        self._t_lastread.setWordWrap(True)
        self._t_lastread.setStyleSheet("color:#225; font-weight:bold")
        form = QFormLayout()
        form.addRow("Name", self._t_name)
        form.addRow("Type", self._t_type)
        form.addRow("Match", self._t_mode)
        form.addRow("Value", self._t_value)
        form.addRow("Rotation", self._t_rotation)
        form.addRow("Search ↔ L/R", self._t_search_x)
        form.addRow("Search ↕ T/B", self._t_search_y)
        form.addRow("Min confidence", self._t_minconf)
        form.addRow("Font", self._t_font)
        form.addRow("Charset", self._t_charset)
        form.addRow("", self._t_required)
        form.addRow("Last read", self._t_lastread)
        self._tool_form = form
        # rows that only apply to Read (code/text) inspections
        self._match_rows = [
            self._t_mode, self._t_value,
            self._t_rotation, self._t_search_x, self._t_search_y, self._t_minconf, self._t_required,
        ]
        # per-type editor for the general tools (presence/measure/colour/template)
        self._general_form = QFormLayout()
        self._general_form.setContentsMargins(0, 0, 0, 0)
        self._general_container = QWidget()
        self._general_container.setLayout(self._general_form)
        self._gen_widgets: dict = {}

        form_w = QWidget()
        form_w.setLayout(form)
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(form_w)
        outer.addWidget(self._general_container)
        w = QWidget()
        w.setLayout(outer)
        w.hide()
        return w

    def _set_match_rows_visible(self, visible: bool) -> None:
        for widget in self._match_rows:
            self._tool_form.setRowVisible(widget, visible)

    def _sync_tool_inputs(self, mode: str) -> None:
        self._t_value.setEnabled(True)

    # ---- general-tool editor (presence / measure / colour / template) -----
    def _build_general_editor(self, tool) -> None:
        while self._general_form.rowCount():
            self._general_form.removeRow(0)
        self._gen_widgets = {}
        cfg = tool.config or {}
        t = tool.tool_type

        def spin(lo, hi, val, suffix=""):
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(val))
            if suffix:
                s.setSuffix(suffix)
            s.valueChanged.connect(self._general_edited)
            return s

        def combo(items, current):
            c = QComboBox()
            c.addItems(items)
            c.setCurrentText(current)
            c.currentTextChanged.connect(self._general_edited)
            return c

        if t == "presence":
            self._gen_widgets["mode"] = combo(["present", "absent"], cfg.get("mode", "present"))
            self._gen_widgets["min_coverage"] = spin(1, 100, int(cfg.get("min_coverage", 0.05) * 100), " %")
            self._general_form.addRow("Object must be", self._gen_widgets["mode"])
            self._general_form.addRow("Min coverage", self._gen_widgets["min_coverage"])
        elif t == "measure":
            self._gen_widgets["axis"] = combo(["width", "height"], cfg.get("axis", "width"))
            self._gen_widgets["min_px"] = spin(0, 100000, int(cfg.get("min_px", 10)), " px")
            self._gen_widgets["max_px"] = spin(0, 1000000, int(cfg.get("max_px", 10000)), " px")
            self._general_form.addRow("Measure", self._gen_widgets["axis"])
            self._general_form.addRow("Min size", self._gen_widgets["min_px"])
            self._general_form.addRow("Max size", self._gen_widgets["max_px"])
        elif t == "color_check":
            target = cfg.get("target", [128, 128, 128])
            swatch = QLabel()
            swatch.setFixedSize(44, 18)
            swatch.setStyleSheet(f"background: rgb({target[0]},{target[1]},{target[2]}); border:1px solid #888")
            self._gen_widgets["swatch"] = swatch
            pick = QPushButton("Set colour from box")
            pick.clicked.connect(self._pick_color)
            self._gen_widgets["tolerance"] = spin(0, 255, int(cfg.get("tolerance", 40)))
            self._general_form.addRow("Target colour", swatch)
            self._general_form.addRow("", pick)
            self._general_form.addRow("Tolerance", self._gen_widgets["tolerance"])
        elif t == "template_match":
            self._gen_widgets["min_score"] = spin(0, 100, int(cfg.get("min_score", 0.6) * 100), " %")
            recap = QPushButton("Recapture from box")
            recap.clicked.connect(self._recapture_template)
            self._general_form.addRow("Min match", self._gen_widgets["min_score"])
            self._general_form.addRow("", recap)

    def _general_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "tool":
            return
        tool = self._model.regions[self._selected[1]].tools[self._selected[2]]
        gw = self._gen_widgets
        t = tool.tool_type
        if t == "presence":
            tool.config = {"mode": gw["mode"].currentText(), "min_coverage": gw["min_coverage"].value() / 100}
        elif t == "measure":
            tool.config = {"axis": gw["axis"].currentText(), "min_px": gw["min_px"].value(), "max_px": gw["max_px"].value()}
        elif t == "color_check":
            tool.config = {**(tool.config or {}), "tolerance": gw["tolerance"].value()}
        elif t == "template_match":
            tool.config = {**(tool.config or {}), "min_score": gw["min_score"].value() / 100}
        self._last_results = None

    def _pick_color(self) -> None:
        roi = self._selected_abs_roi()
        if roi is None or self._selected[0] != "tool":
            return
        x, y, w, h = roi
        crop = np.asarray(self._teach_image())[y : y + h, x : x + w, :3]
        mean = crop.reshape(-1, 3).mean(axis=0).astype(int)
        tool = self._model.regions[self._selected[1]].tools[self._selected[2]]
        tool.config = {**(tool.config or {}), "target": [int(mean[0]), int(mean[1]), int(mean[2])]}
        self._gen_widgets["swatch"].setStyleSheet(
            f"background: rgb({mean[0]},{mean[1]},{mean[2]}); border:1px solid #888"
        )
        self._status.setText(f"Target colour set to rgb({mean[0]},{mean[1]},{mean[2]}) from the box.")

    def _recapture_template(self) -> None:
        roi = self._selected_abs_roi()
        if roi is None or self._selected[0] != "tool":
            return
        from ..tools.general import register_template

        x, y, w, h = roi
        tool = self._model.regions[self._selected[1]].tools[self._selected[2]]
        tool.config = {**(tool.config or {}), "template": register_template(self._teach_image()[y : y + h, x : x + w])}
        self._status.setText("Golden template recaptured from the current box.")

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
            prefix = {"code_verify": "code", "ocv_text": "text", "ocv_font": "ocv"}.get(type_key, type_key)
            tool_id = prefix + str(count)
            if type_key in MATCH_TOOLS:
                config = tool_config(type_key, "")
            else:
                config = default_config(type_key)
            if type_key in ("code_verify", "ocv_text", "ocv_font"):
                config["search_x"] = 20  # outer search region (print drift)
                config["search_y"] = 20
            if type_key == "template_match":  # capture the golden patch from the ROI
                from ..tools.general import register_template

                config = {"template": register_template(self._teach_image()[y : y + h, x : x + w]), "min_score": 0.6}
            t_idx = self._model.add_tool(region_index, tool_id, type_key, rel, config)
            self._selected = ("tool", region_index, t_idx)
            self._set_guide(
                "Added. Set its options below (or leave defaults), then add more or click <b>Test</b>."
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
        self._resize_tree()
        self._select_in_tree(self._selected)
        self._tree.blockSignals(False)
        self._load_properties()

    def _resize_tree(self) -> None:
        """Size the inspection plan to its content: 4 rows minimum, growing with
        each added line, capped so the properties panel stays in view."""
        rows = 0
        for r in range(self._tree.topLevelItemCount()):
            rows += 1 + self._tree.topLevelItem(r).childCount()
        rows = max(4, min(rows, 12))
        row_h = max(22, self._tree.fontMetrics().height() + 9)
        self._tree.setFixedHeight(rows * row_h + 14)

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
            self._p_locator.setText("set ✓" if getattr(region, "fixture", None) else "none")
            self._product_props.show()
            self._tool_props.hide()
        else:
            region = self._model.regions[self._selected[1]]
            tool = region.tools[self._selected[2]]
            self._t_name.setText(tool.tool_id)
            self._t_type.setText(_FRIENDLY.get(tool.tool_type, tool.tool_type))
            if tool.tool_type not in MATCH_TOOLS:
                # general tool (presence/measure/colour/template): hide the Read-only
                # rows and show a dedicated editor for this tool's settings
                self._set_match_rows_visible(False)
                self._tool_form.setRowVisible(self._t_lastread, False)
                self._build_general_editor(tool)
                self._general_container.show()
                self._product_props.hide()
                self._tool_props.show()
                self._loading = False
                return
            self._general_container.hide()
            self._set_match_rows_visible(True)
            self._tool_form.setRowVisible(self._t_lastread, True)
            self._tool_form.labelForField(self._t_lastread).setText("Last read")
            info = read_config(tool.tool_type, tool.config)
            self._t_mode.clear()
            self._t_mode.addItems(modes_for(tool.tool_type))
            self._t_mode.setCurrentText(info["mode"])
            self._t_value.setText(info["value"])
            self._t_value.setPlaceholderText(value_hint(tool.tool_type, info["mode"]))
            rotation_index = self._t_rotation.findData(info["rotation"])
            self._t_rotation.setCurrentIndex(rotation_index if rotation_index >= 0 else 0)
            self._t_required.setChecked(tool.config.get("required", True))
            self._t_minconf.setValue(int(round((tool.config.get("min_confidence", 0) or 0) * 100)))
            _legacy = int(tool.config.get("search_margin", 0) or 0)
            self._t_search_x.setValue(int(tool.config.get("search_x", _legacy) or 0))
            self._t_search_y.setValue(int(tool.config.get("search_y", _legacy) or 0))
            is_font_tool = tool.tool_type == "ocv_font"
            self._tool_form.setRowVisible(self._t_font, is_font_tool)
            self._tool_form.setRowVisible(self._t_charset, is_font_tool)
            idx = self._t_charset.findData((tool.config or {}).get("charset", "") or "")
            self._t_charset.setCurrentIndex(idx if idx >= 0 else 0)
            if is_font_tool:
                self._load_fonts(tool)
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

    def _load_engines(self, tool) -> None:
        """Populate the Engine selector with the available reading providers."""
        from ..tools.readers import available_code_readers, available_text_readers

        names = available_code_readers() if tool.tool_type == "code_verify" else available_text_readers()
        self._t_reader.clear()
        for name in names:
            label = "Built-in" if name == "builtin" else name
            self._t_reader.addItem(label, name)
        current = (tool.config or {}).get("reader", "builtin")
        idx = self._t_reader.findData(current)
        self._t_reader.setCurrentIndex(idx if idx >= 0 else 0)

    def _load_fonts(self, tool) -> None:
        """Populate the Font selector from the trained-font library."""
        self._t_font.blockSignals(True)
        self._t_font.clear()
        self._fonts_index = {}
        if self._sf is not None:
            from ..db.fonts import FontRepository

            for f in FontRepository(self._sf).list_fonts():
                self._t_font.addItem(f"{f['name']}  ({f['samples']} samples)", f["id"])
                self._fonts_index[f["id"]] = f
        current = (tool.config or {}).get("font_id")
        idx = self._t_font.findData(current)
        if idx >= 0:
            self._t_font.setCurrentIndex(idx)
        elif self._t_font.count() and not (tool.config or {}).get("font"):
            self._t_font.setCurrentIndex(0)
            self._embed_font(tool, self._t_font.currentData())
        self._t_font.blockSignals(False)

    def _embed_font(self, tool, font_id) -> None:
        """Embed the selected font's glyphs into the tool config (recipes stay
        self-contained; retraining a font later doesn't silently change approved
        recipes — re-teach to pick up new training)."""
        if font_id is None or self._sf is None:
            return
        from ..db.fonts import FontRepository

        try:
            name, glyphs, dot_kernel = FontRepository(self._sf).glyphs(font_id)
        except Exception:
            return
        config = dict(tool.config or {})
        config.update({
            "font": glyphs, "font_name": name, "font_id": font_id,
            "dot_kernel": dot_kernel, "min_area": 6,
        })
        tool.config = config

    def _font_changed(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "tool":
            return
        tool = self._model.regions[self._selected[1]].tools[self._selected[2]]
        if tool.tool_type != "ocv_font":
            return
        self._embed_font(tool, self._t_font.currentData())
        self._last_results = None

    def _tool_edited(self) -> None:
        if self._loading or self._selected is None or self._selected[0] != "tool":
            return
        region = self._model.regions[self._selected[1]]
        tool = region.tools[self._selected[2]]
        tool.tool_id = self._t_name.text()
        if tool.tool_type not in MATCH_TOOLS:
            # general tools: only the name is editable here; keep their config
            item = self._tree.currentItem()
            if item is not None:
                friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
                item.setText(0, f"{tool.tool_id} · {friendly}")
            return
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
        if self._t_minconf.value() > 0:
            cfg["min_confidence"] = self._t_minconf.value() / 100
        if self._t_search_x.value() > 0:
            cfg["search_x"] = self._t_search_x.value()
        if self._t_search_y.value() > 0:
            cfg["search_y"] = self._t_search_y.value()
        if tool.tool_type == "ocv_font":
            for key in FONT_KEYS:  # the trained font must survive match edits
                if key in (tool.config or {}):
                    cfg[key] = tool.config[key]
            if self._t_charset.currentData():
                cfg["charset"] = self._t_charset.currentData()
        tool.config = cfg
        self._t_value.setPlaceholderText(value_hint(tool.tool_type, mode))
        self._sync_tool_inputs(mode)
        item = self._tree.currentItem()
        if item is not None:
            friendly = _FRIENDLY.get(tool.tool_type, tool.tool_type)
            item.setText(0, f"{tool.tool_id} · {friendly}")
        self._last_results = None
        self._refresh_view()

    def _duplicate_selected(self) -> None:
        if self._selected is None or self._selected[0] != "tool":
            self._status.setText("Select an inspection in the plan to duplicate.")
            return
        ri, ti = self._selected[1], self._selected[2]
        src = self._model.regions[ri].tools[ti]
        count = sum(len(r.tools) for r in self._model.regions) + 1
        new_id = ("code" if src.tool_type == "code_verify" else "text") + str(count)
        new_roi = ROI(src.roi.x + 20, src.roi.y + 20, src.roi.w, src.roi.h)
        idx = self._model.add_tool(ri, new_id, src.tool_type, new_roi, dict(src.config))
        self._selected = ("tool", ri, idx)
        self._last_results = None
        self._rebuild_tree()
        self._refresh_view()
        self._set_guide("Duplicated — drag the copy's box/handles to its field, then edit its value.")

    def _clear_locator(self) -> None:
        if self._selected is None or self._selected[0] != "region":
            return
        self._model.regions[self._selected[1]].fixture = None
        self._last_results = None
        self._load_properties()
        self._refresh_view()
        self._status.setText("Part locator cleared.")

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

    # ---- live camera teaching --------------------------------------------
    def _live_tick(self) -> None:
        frame = self._image_provider() if self._image_provider is not None else None
        if frame is not None:
            self._live_frame = frame
            self._image.setImage(frame)  # raw live frame, no ROI overlay

    def _go_live(self) -> None:
        if self._image_provider is None:
            return
        self._live = True
        self._set_guide(
            "● LIVE — position the product in view, then click <b>Snap</b> to freeze it."
        )
        self._live_timer.start()

    def _snap(self) -> None:
        if not self._live:
            return
        self._live_timer.stop()
        self._live = False
        if self._live_frame is not None:
            self._reference = self._live_frame
            self._bank[self._reference_index] = self._live_frame
            self._last_results = None
            self._image.reset_view()
        self._refresh_view()
        self._set_guide(
            "Snapped ✓ — pick <b>Read Code</b>/<b>Read Text</b> and drag a box. "
            "Click <b>Live</b> to reposition."
        )

    # ---- actions ----------------------------------------------------------
    def _test(self) -> None:
        if not any(region.tools for region in self._model.regions):
            self._status.setText("Add at least one inspection (Read Code / Read Text) first.")
            return
        ref = self._reference
        model = self._model
        self._run_async(lambda: model.test(ref), self._test_done,
                        "Testing… (the first run also loads the OCR model — a few seconds)")

    def _test_done(self, results) -> None:
        self._last_results = results
        self._rebuild_tree()  # annotate the inspection plan with ✓/✗ + read values
        self._refresh_view()
        self._status.setText(self._results_summary())

    # --- background test runner (keeps the GUI responsive) ---------------------
    def _run_async(self, fn, on_done, busy_message: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # a test is already running; ignore repeat clicks
        self._pending_done = on_done
        self._status.setText(busy_message)
        self._set_test_enabled(False)
        worker = _TestWorker(fn)
        worker.done.connect(self._on_async_done)      # queued onto the GUI thread
        worker.failed.connect(self._on_async_failed)
        self._worker = worker
        worker.start()

    def _on_async_done(self, result) -> None:
        cb, self._pending_done = self._pending_done, None
        self._worker = None
        self._set_test_enabled(True)
        if cb is not None:
            cb(result)

    def _on_async_failed(self, message: str) -> None:
        self._pending_done = None
        self._worker = None
        self._set_test_enabled(True)
        self._status.setText(f"Test failed: {message}")

    def _set_test_enabled(self, on: bool) -> None:
        self._test_btn.setEnabled(on)
        self._test_all_btn.setEnabled(on)

    def closeEvent(self, event) -> None:
        # stop the live feed and release the camera (on_close closes the source)
        self._live_timer.stop()
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass
        # Don't let a running background test outlive the window (a QThread
        # destroyed while running crashes). Wait briefly for it to finish.
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(5000)
        super().closeEvent(event)

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
                scores = (tr.detail or {}).get("char_scores") or []
                if scores and not tr.passed:
                    detail += "  [chars " + " ".join(f"{v:.2f}" for v in scores) + "]"
                lines.append(f"   {mark} {tr.tool_id}: read “{read}”{detail}")
        lines += self._locator_diagnostics()
        lines += self._quality_warnings()
        return "\n".join(lines)

    def _quality_warnings(self) -> list[str]:
        """Documented classical-OCV floors: chars >= ~20px tall, >= ~30 grey
        levels of contrast — warn at teach time, when it's fixable."""
        from ..tools.transform import print_quality

        teach = self._teach_image()
        out = []
        for region in self._model.regions:
            for tool in region.tools:
                if tool.tool_type not in ("ocv_text", "ocv_font", "code_verify"):
                    continue
                x = region.roi.x + tool.roi.x
                y = region.roi.y + tool.roi.y
                crop = teach[y : y + tool.roi.h, x : x + tool.roi.w]
                if crop.size == 0:
                    continue
                quality = print_quality(crop)
                for warning in quality["warnings"]:
                    out.append(f"   ⚠ {tool.tool_id}: {warning}")
        return out

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
                if tool.tool_type == "ocv_font" and not cfg.get("font"):
                    return f"Inspection '{tool.tool_id}' needs a trained font (open Fonts… to train one)."
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

    def _export(self) -> None:
        problem = self._validate()
        if problem:
            self._status.setText("⚠ " + problem)
            return
        from PySide6.QtWidgets import QFileDialog

        from ..db.recipe_io import export_recipe_obj

        name = (self._recipe_name.text().strip() or "recipe").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(self, "Export recipe", f"{name}.json", "Recipe (*.json)")
        if not path:
            return
        try:
            export_recipe_obj(self._model.to_recipe(), path)
        except Exception as exc:
            self._status.setText(f"Export failed: {exc}")
            return
        self._status.setText(f"Recipe exported to {path}")

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


