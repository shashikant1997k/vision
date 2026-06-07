from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Live")
        self._recipe = recipe
        self._camera_factory = camera_factory
        self._camera_id = camera_id
        self._sf = session_factory
        self._user_id = user_id
        self._teach_window = None
        self._runner: InspectionRunner | None = None
        self._stats = LiveStats()
        self._live = LiveView()

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
        self._stop.setEnabled(False)
        self._start.clicked.connect(self.start)
        self._stop.clicked.connect(self.stop)
        self._teach.clicked.connect(self.open_teach)

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

        side = QVBoxLayout()
        side.addLayout(counters)
        side.addStretch(1)
        side.addLayout(buttons)
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

    def start(self) -> None:
        if self._runner is not None:
            return
        source = self._camera_factory(self._camera_id, None, self._recipe)
        lanes = sorted({region.reject_output for region in self._recipe.regions})
        reject = RejectController(
            [RejectOutputConfig(lane, channel=i + 1) for i, lane in enumerate(lanes)],
            io=SimulatedIO(),
        )
        self._runner = InspectionRunner(
            [(source, self._recipe)],
            SyncPool(),
            stats=self._stats,
            live_view=self._live,
            reject_handler=reject,
        )
        self._runner.start()
        self._timer.start()
        self._start.setEnabled(False)
        self._stop.setEnabled(True)
        self.statusBar().showMessage("Running")

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
