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
        self._recipe_combo.addItem("Demo (built-in)", None)
        if session_factory is not None:
            from ..db.store import RecipeRepository

            for rid, name, version in RecipeRepository(session_factory).list_approved():
                self._recipe_combo.addItem(f"{name} v{version}", rid)
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
        self._settings = QPushButton("Settings…")
        self._stop.setEnabled(False)
        self._start.clicked.connect(self.start)
        self._stop.clicked.connect(self.stop)
        self._teach.clicked.connect(self.open_teach)
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
        buttons.addWidget(self._settings)

        job_form = QFormLayout()
        job_form.addRow("Recipe", self._recipe_combo)
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

        # start a batch if a saved recipe + batch number + DB are available
        if self._sf is not None and recipe_db_id is not None and self._batch_no.text().strip():
            from ..db.batches import BatchService
            from ..db.store import ResultStore

            try:
                self._batch_id = BatchService(self._sf).start(
                    recipe_db_id, self._batch_no.text().strip(), self._user_id
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
        """Grab a reference frame and open the teach screen on it."""
        from .teach_window import TeachWindow

        source = self._camera_factory(self._camera_id, None, self._recipe)
        frame = next(source.frames(), None)
        close = getattr(source, "close", None)
        if callable(close):
            close()
        if frame is None:
            self.statusBar().showMessage("Could not grab a reference frame")
            return
        lanes = sorted({region.reject_output for region in self._recipe.regions})
        self._teach_window = TeachWindow(
            user_id=self._user_id,
            reference_image=frame.image,
            session_factory=self._sf,
            reject_lanes=lanes,
        )
        self._teach_window.resize(960, 540)
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
