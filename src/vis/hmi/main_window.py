from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..common.events import EventBus
from ..engine.pool import SyncPool
from ..io import RejectController, RejectOutputConfig, SimulatedIO
from ..runtime import InspectionRunner, LiveStats, LiveView, draw_overlay
from .image import numpy_to_qpixmap


class MainWindow(QMainWindow):
    """Live-view screen: annotated camera feed + running counters + start/stop.

    Acquisition/inspection run in the InspectionRunner's background threads; the
    UI polls LiveView/LiveStats on a timer (it never blocks on the pipeline).
    """

    remoteStart = Signal()  # emitted from protocol-server threads -> GUI thread
    remoteStop = Signal()

    def __init__(
        self,
        *,
        username,
        recipe,
        camera_factory,
        camera_id="cam1",
        camera_ids=None,
        camera_recipe_ids=None,
        session_factory=None,
        user_id=None,
        report_dir="reports",
        simulation=False,
        alarm_consecutive_rejects=5,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Live")
        self._recipe = recipe
        self._camera_factory = camera_factory
        self._camera_id = camera_id
        self._camera_ids = list(camera_ids) if camera_ids else [camera_id]
        self._cam_recipes: dict = {}
        self._sf = session_factory
        self._user_id = user_id
        self._report_dir = report_dir
        self._simulation = simulation
        self._alarm_threshold = alarm_consecutive_rejects
        # the operator's permissions decide which controls are even shown
        self._perms = None
        if session_factory is not None and user_id is not None:
            from ..security.authz import permissions_for

            with session_factory() as s:
                self._perms = permissions_for(s, user_id)
        self._teach_window = None
        self._settings_window = None
        self._runner: InspectionRunner | None = None
        self._batch_id: int | None = None
        self._stats = LiveStats()
        self._live = LiveView()

        # recipe selector: built-in demo + any approved recipes from the DB
        self._recipe_combo = QComboBox()
        self._reload_btn = QPushButton("↻")
        self._reload_btn.setFixedWidth(38)
        self._reload_btn.setStyleSheet("padding: 6px 2px")
        self._reload_btn.setToolTip("Reload recipes from the database")
        self._reload_btn.clicked.connect(self._reload_recipes)
        self._reload_recipes()
        self._batch_no = QLineEdit()
        self._batch_no.setPlaceholderText("batch no. (optional)")
        self._close_batch = QPushButton("Close batch")
        self._close_batch.setProperty("variant", "primary")
        self._close_batch.setEnabled(False)
        self._close_batch.clicked.connect(self.close_batch)

        # one live view per camera (a single camera shows a single tab)
        from PySide6.QtWidgets import QTabWidget

        self._cam_tabs = QTabWidget()
        self._cam_images: dict = {}
        for cid in self._camera_ids:
            lbl = QLabel("No camera running")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMinimumSize(560, 340)
            lbl.setStyleSheet("background:#111; color:#888")
            self._cam_images[cid] = lbl
            self._cam_tabs.addTab(lbl, cid)
        self._cam_tabs.setTabBarAutoHide(True)  # hide the bar when there's one camera
        self._image = self._cam_images[self._camera_ids[0]]  # primary (settings preview)

        from ..runtime import FailedImageLog

        self._failed_log = FailedImageLog(capacity=100)
        self._review_window = None

        self._total = QLabel("0")
        self._pass = QLabel("0")
        self._fail = QLabel("0")
        self._yield = QLabel("—")
        for label in (self._total, self._pass, self._fail, self._yield):
            label.setStyleSheet("font-size: 15px; font-weight: bold")
        self._state = QLabel("● Idle")
        self._state.setStyleSheet("color:#888; font-weight:bold")
        self._reasons = QLabel("")
        self._reasons.setWordWrap(True)
        self._reasons.setMaximumWidth(360)
        self._reasons.setStyleSheet("color:#a33")

        # real-time results table: one row per camera/lane with counts + a live
        # ✓/✗ for the most recent product on that lane
        self._results_table = QTableWidget(0, 6)
        self._results_table.setHorizontalHeaderLabels(
            ["Camera", "Lane", "Total", "Pass", "Fail", "Live"]
        )
        self._results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._results_table.setSelectionMode(QTableWidget.NoSelection)
        self._results_table.verticalHeader().setVisible(False)
        from PySide6.QtWidgets import QHeaderView

        self._results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_table.setMinimumHeight(120)

        self._start = QPushButton("▶  Start")
        self._start.setProperty("variant", "primary")
        self._stop = QPushButton("■  Stop")
        self._stop.setProperty("variant", "danger")
        self._teach = QPushButton("Teach…")
        self._teach_files = QPushButton("Teach on images…")
        self._emulate = QPushButton("Emulate folder…")
        self._review = QPushButton("Review rejects…")
        self._import = QPushButton("Import recipe…")
        self._fonts = QPushButton("Fonts…")
        self._events_btn = QPushButton("Events…")
        self._comms = QPushButton("Comms…")
        self._stations = QPushButton("Stations…")
        self._admin = QPushButton("Admin…")
        self._settings = QPushButton("Settings…")
        self._stop.setEnabled(False)
        self._start.clicked.connect(self.start)
        self._stop.clicked.connect(self.stop)
        self._teach.clicked.connect(self.open_teach)
        self._teach_files.clicked.connect(self.open_teach_from_files)
        self._emulate.clicked.connect(self.open_emulate)
        self._review.clicked.connect(self.open_review)
        self._import.clicked.connect(self.import_recipe)
        self._fonts.clicked.connect(self.open_fonts)
        self._events_btn.clicked.connect(self.open_events)
        self._comms.clicked.connect(self.open_comms)
        self._stations.clicked.connect(self.open_stations)
        self._admin.clicked.connect(self.open_admin)
        self._settings.clicked.connect(self.open_settings)

        # role-gate the engineering/admin controls: operators get a clean
        # run-only screen (industry practice — not just backend permission errors)
        from ..security.authz import Perm

        for widget, perm in (
            (self._teach, Perm.RECIPE_CREATE),
            (self._teach_files, Perm.RECIPE_CREATE),
            (self._emulate, Perm.RECIPE_CREATE),
            (self._import, Perm.RECIPE_CREATE),
            (self._fonts, Perm.RECIPE_CREATE),
            (self._comms, Perm.STATION_MANAGE),
            (self._stations, Perm.STATION_MANAGE),
            (self._settings, Perm.STATION_MANAGE),
        ):
            widget.setVisible(self._can(perm))
        self._admin.setVisible(self._can(Perm.USER_MANAGE) or self._can(Perm.AUDIT_VIEW))

        # compact aggregate strip beneath the per-camera/lane table
        totals_row = QHBoxLayout()
        for caption, label in (
            ("Total", self._total), ("Pass", self._pass),
            ("Reject", self._fail), ("Yield", self._yield),
        ):
            cap = QLabel(caption)
            cap.setStyleSheet("color:#667")
            totals_row.addWidget(cap)
            totals_row.addWidget(label)
            totals_row.addSpacing(10)
        totals_row.addStretch(1)

        # grouped rows so buttons never get crushed; rows whose buttons are all
        # role-hidden collapse to nothing (operators see just the run row)
        buttons = QVBoxLayout()
        run_row = QHBoxLayout()
        run_row.addWidget(self._start, 1)
        run_row.addWidget(self._stop, 1)
        run_row.addWidget(self._review, 1)
        run_row.addWidget(self._events_btn, 1)
        buttons.addLayout(run_row)
        tools_row = QHBoxLayout()
        for w in (self._teach, self._teach_files, self._emulate, self._import, self._fonts):
            tools_row.addWidget(w, 1)
        buttons.addLayout(tools_row)
        admin_row = QHBoxLayout()
        for w in (self._comms, self._stations, self._admin, self._settings):
            admin_row.addWidget(w, 1)
        buttons.addLayout(admin_row)

        recipe_row = QHBoxLayout()
        recipe_row.addWidget(self._recipe_combo, 1)
        recipe_row.addWidget(self._reload_btn)
        job_form = QFormLayout()
        # primary recipe (cam 1); each extra camera gets its own recipe selector
        self._cam_recipe_combos = {self._camera_ids[0]: self._recipe_combo}
        multi = len(self._camera_ids) > 1
        job_form.addRow("Recipe " + (self._camera_ids[0] if multi else ""), recipe_row)
        for cid in self._camera_ids[1:]:
            combo = QComboBox()
            self._cam_recipe_combos[cid] = combo
            job_form.addRow(f"Recipe {cid}", combo)
        self._reload_recipes()  # populate the per-camera combos now they exist
        for cid, rid in (camera_recipe_ids or {}).items():  # pre-select from station config
            combo = self._cam_recipe_combos.get(cid)
            if combo is not None:
                idx = combo.findData(rid)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        job_form.addRow("Batch", self._batch_no)

        side = QVBoxLayout()
        side.addLayout(job_form)
        side.addWidget(self._state)
        side.addWidget(self._results_table, 1)  # the live results board
        side.addLayout(totals_row)
        side.addWidget(self._reasons)
        side.addLayout(buttons)
        side.addWidget(self._close_batch)
        side_widget = QWidget()
        side_widget.setLayout(side)

        # left side: an unmissable banner when running on a simulated source
        left = QVBoxLayout()
        if self._simulation:
            banner = QLabel("⚠ SIMULATION MODE — simulated camera, not production data")
            banner.setAlignment(Qt.AlignCenter)
            banner.setStyleSheet(
                "background:#b8860b; color:white; font-weight:bold; padding:6px"
            )
            left.addWidget(banner)
        left.addWidget(self._cam_tabs, 1)
        left_widget = QWidget()
        left_widget.setLayout(left)

        root = QHBoxLayout()
        # the camera feed gets the space; the control/results panel stays compact
        side_widget.setMaximumWidth(520)
        self._results_table.horizontalHeader().setMinimumSectionSize(46)
        root.addWidget(left_widget, 1)
        root.addWidget(side_widget, 0)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self.statusBar().showMessage(f"Logged in as {username}")

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

        # third-party integration (docs/12): TCP server + 24V line signals
        self._events = None
        self._proto = None
        self._signals = None
        self.remoteStart.connect(self.start)
        self.remoteStop.connect(self.stop)
        if self._sf is not None:
            from ..db.app_settings import EventService

            self._events = EventService(self._sf)
            from .comms_window import load_comms_config

            try:
                self._apply_comms(load_comms_config(self._sf))
            except Exception:
                pass  # comms must never block the HMI from opening

    def _reload_recipes(self) -> None:
        """Repopulate every camera's recipe selector from the DB (demo + approved)."""
        combos = list(getattr(self, "_cam_recipe_combos", {}).values()) or [self._recipe_combo]
        items = [("Demo (built-in)", None)]
        if self._sf is not None:
            from ..db.store import RecipeRepository

            for rid, name, version in RecipeRepository(self._sf).list_approved():
                items.append((f"{name} v{version}", rid))
        for combo in combos:
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for label, data in items:
                combo.addItem(label, data)
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._reload_recipes()  # refresh after returning from the teach window
        super().changeEvent(event)

    def _resolve_recipe_for(self, combo):
        """Return (domain_recipe, recipe_db_id|None) for a recipe selector."""
        recipe_db_id = combo.currentData()
        if recipe_db_id is None or self._sf is None:
            return self._recipe, None
        from ..db.store import RecipeRepository

        return RecipeRepository(self._sf).load(recipe_db_id), recipe_db_id

    def _resolve_recipe(self):
        """The primary (cam 1) recipe — used for teach/emulate/settings."""
        return self._resolve_recipe_for(self._recipe_combo)

    def start(self) -> None:
        if self._runner is not None:
            return
        self._recipe, recipe_db_id = self._resolve_recipe()
        bus = EventBus()
        batch_no = self._batch_no.text().strip()
        variable_data: dict = {}

        if self._sf is not None and recipe_db_id is not None:
            from ..runtime.resolve import required_batch_fields, resolve_batch_fields

            fields = required_batch_fields(self._recipe)
            if fields:
                # the recipe is fed values before every batch — collect them now
                from .batch_data_dialog import BatchDataDialog

                dialog = BatchDataDialog(batch_no, fields, self)
                if dialog.exec() != QDialog.Accepted:
                    return
                batch_no = dialog.batch_no()
                variable_data = dialog.values()
                self._recipe = resolve_batch_fields(self._recipe, variable_data)

            if batch_no:
                from ..db.batches import BatchService
                from ..db.store import ResultStore

                try:
                    self._batch_id = BatchService(self._sf).start(
                        recipe_db_id, batch_no, self._user_id, variable_data=variable_data
                    )
                except Exception as exc:
                    self.statusBar().showMessage(f"Batch start failed: {exc}")
                    return
                bus.subscribe("inspection.result", ResultStore(self._sf, batch_id=self._batch_id).on_result)
                self._close_batch.setEnabled(True)
                self._log_event("info", "batch", f"Batch {batch_no} started")

        # build one assignment per camera, each with its own selected recipe
        # (the primary recipe drives the batch; batch values apply to all cameras)
        from ..runtime.resolve import resolve_batch_fields

        self._cam_recipes = {}
        if self._proto is not None:
            bus.subscribe("inspection.result", self._proto.on_result)
        if self._signals is not None:
            bus.subscribe("inspection.result", self._signals.on_result)
        assignments = []
        for cid in self._camera_ids:
            if cid == self._camera_ids[0]:
                cam_recipe = self._recipe  # already resolved above
            else:
                cam_recipe, _ = self._resolve_recipe_for(self._cam_recipe_combos[cid])
                if variable_data:
                    cam_recipe = resolve_batch_fields(cam_recipe, variable_data)
            self._cam_recipes[cid] = cam_recipe
            assignments.append((self._camera_factory(cid, None, cam_recipe), cam_recipe))
        lanes = sorted(
            {r.reject_output for rec in self._cam_recipes.values() for r in rec.regions}
        )
        reject = RejectController(
            [RejectOutputConfig(lane, channel=i + 1) for i, lane in enumerate(lanes)],
            io=SimulatedIO(),
        )
        self._runner = InspectionRunner(
            assignments,
            SyncPool(),
            bus=bus,
            stats=self._stats,
            live_view=self._live,
            reject_handler=reject,
            failed_log=self._failed_log,
        )
        self._runner.start()
        self._timer.start()
        self._start.setEnabled(False)
        self._stop.setEnabled(True)
        if self._signals is not None:
            self._signals.set_running(True)
        if self._proto is not None:
            self._proto.push_state(True, batch_no or None)
        self._log_event("info", "run", f"Inspection started ({'batch ' + batch_no if self._batch_id else 'test mode'})")
        if self._batch_id is not None:
            self._set_state("Running", "#1a8")
            self.statusBar().showMessage(f"Running — batch {batch_no}")
        else:
            # no batch = nothing is being recorded; make that unmistakable
            self._set_state("Running (TEST — no batch)", "#b8860b")
            self.statusBar().showMessage(
                "Running WITHOUT a batch — results are not being recorded (test mode)"
            )

    # ---- third-party integration (TCP + 24V) -----------------------------
    def _log_event(self, severity: str, source: str, message: str) -> None:
        if self._events is not None:
            try:
                self._events.log(severity, source, message, batch_id=self._batch_id)
            except Exception:
                pass

    def _apply_comms(self, config: dict) -> None:
        """(Re)start the integration server + line signals from saved config."""
        if self._proto is not None:
            self._proto.stop()
            self._proto = None
        if self._signals is not None:
            self._signals.close()
            self._signals = None

        signal_map = None
        if config and any((config.get("signals") or {}).get(k) for k in
                          ("ready", "running", "pass_pulse", "reject_pulse", "alarm", "heartbeat")):
            from ..io.signals import LineSignals, SignalMap

            io = None
            if config.get("io_backend") == "modbus" and config.get("io_host"):
                from ..io import ModbusTcpIO

                io = ModbusTcpIO(config["io_host"], int(config.get("io_port", 502)))
            signal_map = SignalMap.from_dict(config.get("signals"))
            self._signals = LineSignals(io, signal_map)
            self._signals.set_ready(True)
            self._signals.start_heartbeat()

        if config and config.get("tcp_enabled"):
            from ..integrations.vis_protocol import VisProtocolServer

            callbacks = {
                "get_status": self._proto_status,
                "get_counters": self._proto_counters,
                "list_recipes": self._proto_recipes,
            }
            if config.get("allow_remote_start"):
                callbacks["start"] = self.remoteStart.emit  # thread-safe -> GUI
                callbacks["stop"] = self.remoteStop.emit
            self._proto = VisProtocolServer(port=int(config.get("tcp_port", 9410)),
                                            callbacks=callbacks).start()

    def _proto_status(self) -> dict:
        return {
            "running": self._runner is not None,
            "batch": self._batch_no.text().strip() or None,
            "recipe": self._recipe_combo.currentText(),
            "alarm": "ALARM" in self._state.text() or None,
        }

    def _proto_counters(self) -> dict:
        totals = self._stats.totals()
        return {"total": totals["total"], "passed": totals["passed"],
                "failed": totals["failed"], "yield": round(totals.get("yield", 0.0), 2)}

    def _proto_recipes(self) -> list:
        return [
            {"id": self._recipe_combo.itemData(i), "name": self._recipe_combo.itemText(i)}
            for i in range(self._recipe_combo.count())
        ]

    def comms_status(self) -> str:
        if self._proto is None:
            return "Integration server: disabled."
        return (f"Integration server: listening on port {self._proto.port}, "
                f"{self._proto.client_count()} client(s) connected.")

    def open_events(self) -> None:
        if self._sf is None:
            self.statusBar().showMessage("No database — events unavailable.")
            return
        from .events_window import EventsWindow

        self._events_window = EventsWindow(self._sf, self)
        self._events_window.resize(760, 480)
        self._events_window.show()

    def open_comms(self) -> None:
        if self._sf is None:
            self.statusBar().showMessage("No database — comms unavailable.")
            return
        from .comms_window import CommsWindow

        self._comms_window = CommsWindow(
            self._sf, apply_callback=self._apply_comms, status_provider=self.comms_status, parent=self
        )
        self._comms_window.resize(520, 620)
        self._comms_window.show()

    def closeEvent(self, event) -> None:  # fail-safe: drop READY, stop server
        if self._signals is not None:
            self._signals.close()
        if self._proto is not None:
            self._proto.stop()
        super().closeEvent(event)

    def _can(self, perm: str) -> bool:
        """True when the logged-in user holds `perm` (no DB/dev mode = allow)."""
        return self._perms is None or perm in self._perms

    def _set_state(self, text: str, color: str) -> None:
        self._state.setText(f"● {text}")
        self._state.setStyleSheet(f"color:{color}; font-weight:bold")

    def close_batch(self) -> None:
        if self._batch_id is None or self._sf is None:
            return
        from .approve_dialog import ApproveDialog

        dialog = ApproveDialog(self)
        dialog.setWindowTitle("Release batch — electronic signature")
        if dialog.exec() != QDialog.Accepted:
            return
        from ..db.batches import BatchService

        try:
            BatchService(self._sf).close(
                self._batch_id, self._user_id, dialog.password_value, dialog.meaning_value
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Batch release failed: {exc}")
            return

        from ..reporting.batch_report import write_batch_report

        released_id = self._batch_id
        try:
            html_path, _ = write_batch_report(self._sf, released_id, self._report_dir)
            self.statusBar().showMessage(f"Batch #{released_id} released — report: {html_path}")
        except Exception as exc:
            self.statusBar().showMessage(f"Batch #{released_id} released; report failed: {exc}")
        self._log_event("info", "batch", f"Batch #{released_id} released")
        self._batch_id = None
        self._close_batch.setEnabled(False)

    def stop(self) -> None:
        if self._runner is not None:
            self._runner.stop()
            self._runner.join()
            self._runner = None
        self._timer.stop()
        self._refresh()  # final counter update
        self._start.setEnabled(True)
        self._stop.setEnabled(False)
        self._set_state("Idle", "#888")
        if self._signals is not None:
            self._signals.set_running(False)
        if self._proto is not None:
            self._proto.push_state(False, None)
        self._log_event("info", "run", "Inspection stopped")
        self.statusBar().showMessage("Stopped")

    def import_recipe(self) -> None:
        """Import a recipe JSON file as a new draft (re-approval required)."""
        if self._sf is None:
            self.statusBar().showMessage("No database — cannot import recipes.")
            return
        from PySide6.QtWidgets import QFileDialog

        from ..db.recipe_io import import_recipe

        path, _ = QFileDialog.getOpenFileName(self, "Import recipe", "", "Recipe (*.json)")
        if not path:
            return
        try:
            new_id = import_recipe(self._sf, path, self._user_id)
        except Exception as exc:
            self.statusBar().showMessage(f"Import failed: {exc}")
            return
        self._reload_recipes()
        self.statusBar().showMessage(f"Imported recipe as draft #{new_id} — approve it to use on the line.")

    def open_fonts(self) -> None:
        """Open the OCV font-training library."""
        if self._sf is None:
            self.statusBar().showMessage("No database — font library unavailable.")
            return
        from .font_window import FontManagerWindow

        self._fonts_window = FontManagerWindow(self._sf, self._user_id, self)
        self._fonts_window.resize(640, 420)
        self._fonts_window.show()

    def open_stations(self) -> None:
        """Open the station/camera admin (define cameras + assign recipes)."""
        if self._sf is None:
            self.statusBar().showMessage("No database — station config unavailable.")
            return
        from .station_window import StationConfigWindow

        self._stations_window = StationConfigWindow(self._sf, self._user_id, self)
        self._stations_window.resize(560, 480)
        self._stations_window.show()

    def open_admin(self) -> None:
        """Open the admin hub: users, products, batches & reports, audit log."""
        if self._sf is None:
            self.statusBar().showMessage("No database — admin unavailable.")
            return
        from .admin_window import AdminWindow

        self._admin_window = AdminWindow(self._sf, self._user_id, report_dir=self._report_dir, parent=self)
        self._admin_window.resize(820, 560)
        self._admin_window.show()

    def open_review(self) -> None:
        """Open the reject-review filmstrip over the captured failed images."""
        if len(self._failed_log) == 0:
            self.statusBar().showMessage("No rejects to review yet.")
            return
        from .review_window import ReviewWindow

        self._review_window = ReviewWindow(self._failed_log, self._recipe, self)
        self._review_window.resize(900, 600)
        self._review_window.show()

    def open_teach(self) -> None:
        """Acquire a set of product images from the line, then open Teach on them
        (pick the reference from the filmstrip and mark ROIs on a real product)."""

        images = []
        source = self._camera_factory(self._camera_id, None, self._recipe)
        for frame in source.frames():
            images.append(frame.image)
            if len(images) >= 50:
                break
        close = getattr(source, "close", None)
        if callable(close):
            close()
        if not images:
            self.statusBar().showMessage("Could not acquire reference images")
            return
        self.statusBar().showMessage(f"Acquired {len(images)} images for teaching")
        self._open_teach_with_images(images)

    def open_teach_from_files(self) -> None:
        """Load product images from disk and teach on them (your own samples)."""
        from PySide6.QtWidgets import QFileDialog

        from ..camera.file_source import load_image

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select product images to teach on",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not paths:
            return
        images = []
        for path in paths:
            try:
                images.append(load_image(path))
            except Exception:
                pass
        if not images:
            self.statusBar().showMessage("Could not load the selected images")
            return
        self.statusBar().showMessage(f"Loaded {len(images)} image(s) for teaching")
        self._open_teach_with_images(images)

    def open_emulate(self) -> None:
        """Run the selected recipe over a folder of saved images (offline playback):
        sorts annotated pass/fail images and writes results.csv."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ..runtime.emulate import emulate_folder

        folder = QFileDialog.getExistingDirectory(self, "Select a folder of product images")
        if not folder:
            return
        recipe, _ = self._resolve_recipe()
        out = Path(folder) / "emulation_results"
        self.statusBar().showMessage("Emulating… (running the recipe over the folder)")
        try:
            summary = emulate_folder(recipe, folder, out)
        except Exception as exc:
            self.statusBar().showMessage(f"Emulation failed: {exc}")
            return
        self.statusBar().showMessage(
            f"Emulated {summary.total} images: {summary.passed} pass, "
            f"{summary.failed} fail — annotated images + results.csv in {out}"
        )

    def _open_teach_with_images(self, images) -> None:
        from .teach_window import TeachWindow

        lanes = sorted({region.reject_output for region in self._recipe.regions})
        self._teach_window = TeachWindow(
            user_id=self._user_id,
            reference_image=images[0],
            reference_images=images,
            session_factory=self._sf,
            reject_lanes=lanes,
        )
        self._teach_window.resize(1040, 600)
        self._teach_window.show()

    def open_settings(self) -> None:
        """Open the camera-settings screen with a live preview from the source."""
        from .settings_window import CameraSettingsWindow

        source = self._camera_factory(self._camera_id, None, self._recipe)
        state = {"gen": source.frames()}

        def provider():
            try:
                frame = next(state["gen"], None)
                if frame is None:
                    state["gen"] = self._camera_factory(self._camera_id, None, self._recipe).frames()
                    frame = next(state["gen"], None)
                return frame.image if frame is not None else None
            except Exception:
                return None  # a bad preview must never block the settings screen

        self._settings_window = CameraSettingsWindow(
            image_provider=provider,
            apply_callback=getattr(source, "apply_settings", None),
        )
        self._settings_window.resize(900, 480)
        self._settings_window.show()

    def _update_results_table(self, snap: dict) -> None:
        """One row per camera/lane: counts plus a live ✓/✗ for the most recent
        product on that lane."""
        rows = []
        for cid in sorted(snap):
            for lane_name in sorted(snap[cid].get("lanes", {})):
                lane = snap[cid]["lanes"][lane_name]
                rows.append((cid, lane_name, lane["total"], lane["passed"], lane["failed"], lane["last"]))
        self._results_table.setRowCount(len(rows))
        live_font = QFont()
        live_font.setPointSize(18)
        live_font.setBold(True)
        for r, (cid, lane_name, total, passed, failed, last) in enumerate(rows):
            for c, value in enumerate((cid, lane_name, total, passed, failed)):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter)
                if c == 3:
                    item.setForeground(QColor(0, 140, 0))
                elif c == 4:
                    item.setForeground(QColor(200, 0, 0))
                self._results_table.setItem(r, c, item)
            live = QTableWidgetItem("—" if last is None else ("✓" if last else "✗"))
            live.setTextAlignment(Qt.AlignCenter)
            live.setFont(live_font)
            if last is not None:
                live.setForeground(QColor(0, 160, 0) if last else QColor(210, 0, 0))
            self._results_table.setItem(r, 5, live)

    def _refresh(self) -> None:
        snap = self._stats.snapshot()
        for cid, label in self._cam_images.items():
            latest = self._live.latest(cid)
            if latest is not None:
                frame, results = latest
                recipe = self._cam_recipes.get(cid, self._recipe)
                annotated = draw_overlay(frame.image, recipe, results)
                pixmap = numpy_to_qpixmap(annotated)
                label.setPixmap(
                    pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            cam = snap.get(cid, {})
            if cam:  # per-camera pass/fail on the tab label
                idx = list(self._cam_images).index(cid)
                self._cam_tabs.setTabText(idx, f"{cid}  {cam.get('passed', 0)}✓/{cam.get('failed', 0)}✗")
        self._update_results_table(snap)
        totals = self._stats.totals()
        self._total.setText(str(totals["total"]))
        self._pass.setText(str(totals["passed"]))
        self._fail.setText(str(totals["failed"]))
        self._yield.setText(f"{totals.get('yield', 0.0):.1f} %" if totals["total"] else "—")
        reasons = self._stats.reject_reasons()
        if reasons:
            top = ", ".join(f"{name}×{n}" for name, n in list(reasons.items())[:4])
            self._reasons.setText(f"Top reject reasons: {top}")
        else:
            self._reasons.setText("")
        self._review.setText(f"Review rejects… ({len(self._failed_log)})")

        # GMP line-stop: N consecutive rejects means a systematic failure (e.g.
        # the coder stopped printing) — stop the line and alarm, don't keep ejecting
        if self._runner is not None and self._alarm_threshold:
            streak = self._stats.consecutive_failures()
            if streak >= self._alarm_threshold:
                self.stop()
                self._set_state(f"ALARM — {streak} consecutive rejects, line stopped", "#c22")
                message = (f"ALARM: {streak} consecutive rejects — line stopped. "
                           "Check the printer/coder and product feed, then review rejects.")
                self.statusBar().showMessage(message)
                if self._signals is not None:
                    self._signals.set_alarm(True)
                if self._proto is not None:
                    self._proto.push_alarm("CONSECUTIVE_REJECTS", message)
                self._log_event("alarm", "line", message)
                return

        # auto-stop when a bounded source (e.g. sim/file) has finished
        if self._runner is not None and not self._runner.is_running():
            self.stop()
