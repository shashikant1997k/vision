from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
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

    def __init__(
        self,
        *,
        username,
        recipe,
        camera_factory,
        camera_id="cam1",
        session_factory=None,
        user_id=None,
        report_dir="reports",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Live")
        self._recipe = recipe
        self._camera_factory = camera_factory
        self._camera_id = camera_id
        self._sf = session_factory
        self._user_id = user_id
        self._report_dir = report_dir
        self._teach_window = None
        self._settings_window = None
        self._runner: InspectionRunner | None = None
        self._batch_id: int | None = None
        self._stats = LiveStats()
        self._live = LiveView()

        # recipe selector: built-in demo + any approved recipes from the DB
        self._recipe_combo = QComboBox()
        self._reload_btn = QPushButton("↻")
        self._reload_btn.setFixedWidth(30)
        self._reload_btn.setToolTip("Reload recipes from the database")
        self._reload_btn.clicked.connect(self._reload_recipes)
        self._reload_recipes()
        self._batch_no = QLineEdit()
        self._batch_no.setPlaceholderText("batch no. (optional)")
        self._close_batch = QPushButton("Close batch")
        self._close_batch.setEnabled(False)
        self._close_batch.clicked.connect(self.close_batch)

        self._image = QLabel("No camera running")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(640, 360)
        self._image.setStyleSheet("background:#111; color:#888")

        self._total = QLabel("0")
        self._pass = QLabel("0")
        self._fail = QLabel("0")
        for label in (self._total, self._pass, self._fail):
            label.setStyleSheet("font-size: 20px; font-weight: bold")

        self._start = QPushButton("Start")
        self._stop = QPushButton("Stop")
        self._teach = QPushButton("Teach…")
        self._teach_files = QPushButton("Teach on images…")
        self._emulate = QPushButton("Emulate folder…")
        self._settings = QPushButton("Settings…")
        self._stop.setEnabled(False)
        self._start.clicked.connect(self.start)
        self._stop.clicked.connect(self.stop)
        self._teach.clicked.connect(self.open_teach)
        self._teach_files.clicked.connect(self.open_teach_from_files)
        self._emulate.clicked.connect(self.open_emulate)
        self._settings.clicked.connect(self.open_settings)

        counters = QGridLayout()
        counters.addWidget(QLabel("Total"), 0, 0)
        counters.addWidget(self._total, 0, 1)
        counters.addWidget(QLabel("Pass"), 1, 0)
        counters.addWidget(self._pass, 1, 1)
        counters.addWidget(QLabel("Reject"), 2, 0)
        counters.addWidget(self._fail, 2, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self._start)
        buttons.addWidget(self._stop)
        buttons.addWidget(self._teach)
        buttons.addWidget(self._teach_files)
        buttons.addWidget(self._emulate)
        buttons.addWidget(self._settings)

        recipe_row = QHBoxLayout()
        recipe_row.addWidget(self._recipe_combo, 1)
        recipe_row.addWidget(self._reload_btn)
        job_form = QFormLayout()
        job_form.addRow("Recipe", recipe_row)
        job_form.addRow("Batch", self._batch_no)

        side = QVBoxLayout()
        side.addLayout(job_form)
        side.addLayout(counters)
        side.addStretch(1)
        side.addLayout(buttons)
        side.addWidget(self._close_batch)
        side_widget = QWidget()
        side_widget.setLayout(side)

        root = QHBoxLayout()
        root.addWidget(self._image, 3)
        root.addWidget(side_widget, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self.statusBar().showMessage(f"Logged in as {username}")

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

    def _reload_recipes(self) -> None:
        """Repopulate the recipe selector from the DB (built-in demo + approved)."""
        current = self._recipe_combo.currentData()
        self._recipe_combo.blockSignals(True)
        self._recipe_combo.clear()
        self._recipe_combo.addItem("Demo (built-in)", None)
        if self._sf is not None:
            from ..db.store import RecipeRepository

            for rid, name, version in RecipeRepository(self._sf).list_approved():
                self._recipe_combo.addItem(f"{name} v{version}", rid)
        idx = self._recipe_combo.findData(current)
        if idx >= 0:
            self._recipe_combo.setCurrentIndex(idx)
        self._recipe_combo.blockSignals(False)

    def changeEvent(self, event) -> None:
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self._reload_recipes()  # refresh after returning from the teach window
        super().changeEvent(event)

    def _resolve_recipe(self):
        """Return (domain_recipe, recipe_db_id|None) for the selected recipe."""
        recipe_db_id = self._recipe_combo.currentData()
        if recipe_db_id is None or self._sf is None:
            return self._recipe, None
        from ..db.store import RecipeRepository

        return RecipeRepository(self._sf).load(recipe_db_id), recipe_db_id

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

        source = self._camera_factory(self._camera_id, None, self._recipe)
        lanes = sorted({region.reject_output for region in self._recipe.regions})
        reject = RejectController(
            [RejectOutputConfig(lane, channel=i + 1) for i, lane in enumerate(lanes)],
            io=SimulatedIO(),
        )
        self._runner = InspectionRunner(
            [(source, self._recipe)],
            SyncPool(),
            bus=bus,
            stats=self._stats,
            live_view=self._live,
            reject_handler=reject,
        )
        self._runner.start()
        self._timer.start()
        self._start.setEnabled(False)
        self._stop.setEnabled(True)
        batch = f" — batch {self._batch_no.text().strip()}" if self._batch_id else ""
        self.statusBar().showMessage(f"Running{batch}")

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
        self._batch_id = None
        self._close_batch.setEnabled(False)

    def stop(self) -> None:
        if self._runner is not None:
            self._runner.stop()
            self._runner.join()
            self._runner = None
        self._timer.stop()
        self._start.setEnabled(True)
        self._stop.setEnabled(False)
        self.statusBar().showMessage("Stopped")

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
            frame = next(state["gen"], None)
            if frame is None:
                state["gen"] = self._camera_factory(self._camera_id, None, self._recipe).frames()
                frame = next(state["gen"], None)
            return frame.image if frame is not None else None

        self._settings_window = CameraSettingsWindow(
            image_provider=provider,
            apply_callback=getattr(source, "apply_settings", None),
        )
        self._settings_window.resize(900, 480)
        self._settings_window.show()

    def _refresh(self) -> None:
        latest = self._live.latest(self._camera_id)
        if latest is not None:
            frame, results = latest
            annotated = draw_overlay(frame.image, self._recipe, results)
            pixmap = numpy_to_qpixmap(annotated)
            self._image.setPixmap(
                pixmap.scaled(self._image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        totals = self._stats.totals()
        self._total.setText(str(totals["total"]))
        self._pass.setText(str(totals["passed"]))
        self._fail.setText(str(totals["failed"]))

        # auto-stop when a bounded source (e.g. sim/file) has finished
        if self._runner is not None and not self._runner.is_running():
            self.stop()
