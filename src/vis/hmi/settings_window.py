from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
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

from ..camera import (
    Calibration,
    CameraSettings,
    FocusAssist,
    TriggerConfig,
    TriggerMode,
)
from .image import numpy_to_qpixmap


class CameraSettingsWindow(QMainWindow):
    """Camera commissioning: live preview + exposure/gain/trigger controls, a
    focus-assist readout, and pixel↔mm calibration. Settings can be applied to
    the camera and saved to the station (audited)."""

    def __init__(
        self,
        *,
        image_provider,
        settings: CameraSettings | None = None,
        apply_callback=None,
        session_factory=None,
        camera_db_id: int | None = None,
        user_id=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vision Inspection — Camera Settings")
        self._image_provider = image_provider
        self._apply_callback = apply_callback
        self._sf = session_factory
        self._camera_db_id = camera_db_id
        self._user_id = user_id
        self._focus = FocusAssist()
        self.calibration = Calibration()
        settings = settings or CameraSettings()

        self._image = QLabel("Preview")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(480, 320)
        self._image.setStyleSheet("background:#111; color:#888")
        self._focus_label = QLabel("focus: —")

        self._exposure = QSpinBox()
        self._exposure.setRange(1, 1_000_000)
        self._exposure.setValue(settings.exposure_us)
        self._gain = QDoubleSpinBox()
        self._gain.setRange(0.0, 48.0)
        self._gain.setValue(settings.gain_db)
        self._fps = QDoubleSpinBox()
        self._fps.setRange(0.1, 1000.0)
        self._fps.setValue(settings.frame_rate)
        self._wb = QComboBox()
        self._wb.addItems(["auto", "manual", "off"])
        self._wb.setCurrentText(settings.white_balance)
        self._packet = QSpinBox()
        self._packet.setRange(576, 9000)
        self._packet.setValue(settings.packet_size)
        self._trigger_mode = QComboBox()
        self._trigger_mode.addItems([m.value for m in TriggerMode])
        self._trigger_mode.setCurrentText(settings.trigger.mode.value)
        self._trigger_source = QLineEdit(settings.trigger.source)

        form = QFormLayout()
        form.addRow("Exposure (µs)", self._exposure)
        form.addRow("Gain (dB)", self._gain)
        form.addRow("Frame rate", self._fps)
        form.addRow("White balance", self._wb)
        form.addRow("Packet size", self._packet)
        form.addRow("Trigger mode", self._trigger_mode)
        form.addRow("Trigger source", self._trigger_source)
        settings_box = QGroupBox("Camera")
        settings_box.setLayout(form)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply)
        self._save_btn = QPushButton("Save to station")
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setEnabled(session_factory is not None and camera_db_id is not None)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(self._save_btn)

        self._cal_pixels = QSpinBox()
        self._cal_pixels.setRange(1, 100_000)
        self._cal_pixels.setValue(200)
        self._cal_mm = QDoubleSpinBox()
        self._cal_mm.setRange(0.01, 10_000.0)
        self._cal_mm.setValue(50.0)
        cal_btn = QPushButton("Calibrate")
        cal_btn.clicked.connect(self._calibrate)
        self._cal_label = QLabel("not calibrated")
        cal_form = QFormLayout()
        cal_form.addRow("Known length (px)", self._cal_pixels)
        cal_form.addRow("equals (mm)", self._cal_mm)
        cal_form.addRow(cal_btn)
        cal_form.addRow("Result", self._cal_label)
        cal_box = QGroupBox("Calibration (pixel ↔ mm)")
        cal_box.setLayout(cal_form)

        self._status = QLabel("")

        side = QVBoxLayout()
        side.addWidget(settings_box)
        side.addLayout(buttons)
        side.addWidget(cal_box)
        side.addWidget(self._status)
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setLayout(side)

        left = QVBoxLayout()
        left.addWidget(self._image, 1)
        left.addWidget(self._focus_label)
        left_widget = QWidget()
        left_widget.setLayout(left)

        root = QHBoxLayout()
        root.addWidget(left_widget, 3)
        root.addWidget(side_widget, 2)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._poll()

    def settings_from_form(self) -> CameraSettings:
        return CameraSettings(
            exposure_us=self._exposure.value(),
            gain_db=self._gain.value(),
            frame_rate=self._fps.value(),
            white_balance=self._wb.currentText(),
            packet_size=self._packet.value(),
            trigger=TriggerConfig(
                mode=TriggerMode(self._trigger_mode.currentText()),
                source=self._trigger_source.text(),
            ),
        )

    def _poll(self) -> None:
        image = self._image_provider()
        if image is None:
            return
        pixmap = numpy_to_qpixmap(image)
        self._image.setPixmap(
            pixmap.scaled(self._image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        score, percent = self._focus.update(image)
        self._focus_label.setText(f"focus: {score:.0f}  ({percent:.0f}% of best)")

    def _apply(self) -> None:
        settings = self.settings_from_form()
        if self._apply_callback is not None:
            self._apply_callback(settings)
        self._status.setText("Applied to camera")

    def _save(self) -> None:
        if self._sf is None or self._camera_db_id is None:
            self._status.setText("No station camera — cannot save")
            return
        from ..db.stations import StationRepository

        try:
            StationRepository(self._sf).update_camera_settings(
                self._camera_db_id, self.settings_from_form(), self._user_id
            )
        except Exception as exc:
            self._status.setText(f"Save failed: {exc}")
            return
        self._status.setText("Saved to station (audited)")

    def _calibrate(self) -> None:
        self.calibration = Calibration.from_known_length(self._cal_pixels.value(), self._cal_mm.value())
        self._cal_label.setText(f"{self.calibration.mm_per_pixel:.4f} mm/px")
