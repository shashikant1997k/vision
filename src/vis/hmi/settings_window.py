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
    QSlider,
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

        # --- exposure & gain (slider + spin box, two-way linked) ---
        self._exposure = QSpinBox()
        self._exposure.setRange(1, 1_000_000)
        self._exposure.setSuffix(" µs")
        self._exposure.setValue(settings.exposure_us)
        self._exposure.setToolTip("Sensor exposure time. Raise in low light; lower to freeze fast motion.")
        self._exposure_slider = QSlider(Qt.Horizontal)
        self._exposure_slider.setRange(50, 50_000)
        _link_int(self._exposure, self._exposure_slider)

        self._gain = QDoubleSpinBox()
        self._gain.setRange(0.0, 48.0)
        self._gain.setSuffix(" dB")
        self._gain.setValue(settings.gain_db)
        self._gain.setToolTip("Analog gain brightens the image but adds noise — prefer more light/exposure first.")
        self._gain_slider = QSlider(Qt.Horizontal)
        self._gain_slider.setRange(0, 480)
        _link_gain(self._gain, self._gain_slider)

        exposure_form = QFormLayout()
        exposure_form.addRow("Exposure", self._exposure)
        exposure_form.addRow("", self._exposure_slider)
        exposure_form.addRow("Gain", self._gain)
        exposure_form.addRow("", self._gain_slider)
        exposure_box = QGroupBox("Exposure / gain")
        exposure_box.setLayout(exposure_form)

        # --- trigger ---
        self._trigger_mode = QComboBox()
        self._trigger_mode.addItems([m.value for m in TriggerMode])
        self._trigger_mode.setCurrentText(settings.trigger.mode.value)
        self._trigger_mode.setToolTip(
            "continuous = free-run; hardware/encoder = capture on a line or encoder signal."
        )
        self._trigger_source = QLineEdit(settings.trigger.source)
        self._trigger_source.setPlaceholderText("e.g. Line1 or EncoderA/B")
        trigger_form = QFormLayout()
        trigger_form.addRow("Mode", self._trigger_mode)
        trigger_form.addRow("Source", self._trigger_source)
        trigger_box = QGroupBox("Trigger")
        trigger_box.setLayout(trigger_form)

        # --- image / transport ---
        self._fps = QDoubleSpinBox()
        self._fps.setRange(0.1, 1000.0)
        self._fps.setSuffix(" fps")
        self._fps.setValue(settings.frame_rate)
        self._wb = QComboBox()
        self._wb.addItems(["auto", "manual", "off"])
        self._wb.setCurrentText(settings.white_balance)
        self._packet = QSpinBox()
        self._packet.setRange(576, 9000)
        self._packet.setValue(settings.packet_size)
        self._packet.setToolTip("GigE packet size. Use 9000 (jumbo frames) for reliable high-bandwidth capture.")
        image_form = QFormLayout()
        image_form.addRow("Frame rate", self._fps)
        image_form.addRow("White balance", self._wb)
        image_form.addRow("Packet size", self._packet)
        image_box = QGroupBox("Image / transport")
        image_box.setLayout(image_form)

        apply_btn = QPushButton("Apply")
        apply_btn.setToolTip("Send these settings to the camera now (the preview updates).")
        apply_btn.clicked.connect(self._apply)
        self._save_btn = QPushButton("Save to station")
        self._save_btn.setToolTip("Persist to the station camera configuration (audited).")
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setEnabled(session_factory is not None and camera_db_id is not None)
        buttons = QHBoxLayout()
        buttons.addWidget(apply_btn)
        buttons.addWidget(self._save_btn)

        # --- calibration ---
        self._cal_pixels = QSpinBox()
        self._cal_pixels.setRange(1, 100_000)
        self._cal_pixels.setSuffix(" px")
        self._cal_pixels.setValue(200)
        self._cal_mm = QDoubleSpinBox()
        self._cal_mm.setRange(0.01, 10_000.0)
        self._cal_mm.setSuffix(" mm")
        self._cal_mm.setValue(50.0)
        cal_btn = QPushButton("Calibrate")
        cal_btn.clicked.connect(self._calibrate)
        self._cal_label = QLabel("not calibrated")
        cal_form = QFormLayout()
        cal_form.addRow("A known length of", self._cal_pixels)
        cal_form.addRow("measures", self._cal_mm)
        cal_form.addRow(cal_btn)
        cal_form.addRow("Scale", self._cal_label)
        cal_box = QGroupBox("Calibration (pixel ↔ mm)")
        cal_box.setLayout(cal_form)

        self._status = QLabel("")
        self._status.setWordWrap(True)

        side = QVBoxLayout()
        side.addWidget(exposure_box)
        side.addWidget(trigger_box)
        side.addWidget(image_box)
        side.addLayout(buttons)
        side.addWidget(cal_box)
        side.addWidget(self._status)
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setLayout(side)

        hint = QLabel("Live preview — adjust until the image is sharp (focus meter peaks) and well exposed.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555")
        left = QVBoxLayout()
        left.addWidget(self._image, 1)
        left.addWidget(self._focus_label)
        left.addWidget(hint)
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


def _link_int(spin, slider) -> None:
    """Two-way link an int QSpinBox with a QSlider (slider clamps to its range)."""

    def to_slider(value):
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), int(value))))
        slider.blockSignals(False)

    def to_spin(value):
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    to_slider(spin.value())
    spin.valueChanged.connect(to_slider)
    slider.valueChanged.connect(to_spin)


def _link_gain(spin, slider) -> None:
    """Two-way link a float gain QDoubleSpinBox with an int slider (×10 scale)."""

    def to_slider(value):
        slider.blockSignals(True)
        slider.setValue(int(round(value * 10)))
        slider.blockSignals(False)

    def to_spin(value):
        spin.blockSignals(True)
        spin.setValue(value / 10.0)
        spin.blockSignals(False)

    to_slider(spin.value())
    spin.valueChanged.connect(to_slider)
    slider.valueChanged.connect(to_spin)
