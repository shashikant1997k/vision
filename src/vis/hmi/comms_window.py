from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..db.app_settings import SettingsService
from ..io.signals import SignalMap

COMMS_KEY = "comms"

DEFAULTS = {
    "tcp_enabled": False,
    "tcp_port": 9410,
    "allow_remote_start": False,
    "io_backend": "simulated",  # simulated | modbus
    "io_host": "",
    "io_port": 502,
    "ntp_server": "",
    "signals": SignalMap().to_dict(),
}


def load_comms_config(session_factory) -> dict:
    config = dict(DEFAULTS)
    saved = SettingsService(session_factory).get(COMMS_KEY) or {}
    config.update(saved)
    merged_signals = dict(DEFAULTS["signals"])
    merged_signals.update(saved.get("signals") or {})
    config["signals"] = merged_signals
    return config


class CommsWindow(QMainWindow):
    """Integration settings (docs/12-integration-protocol.md): the TCP result/
    command server for third-party apps and the 24V hard-wired signal map.
    `apply_callback(config)` lets the live window restart its server/signals."""

    def __init__(self, session_factory, apply_callback=None, status_provider=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Communications — third-party integration")
        self._settings = SettingsService(session_factory)
        self._apply_callback = apply_callback
        self._status_provider = status_provider
        config = load_comms_config(session_factory)

        # --- TCP server ---
        self._tcp_enabled = QCheckBox("Enable the TCP integration server (VIS/1, JSON lines)")
        self._tcp_enabled.setChecked(bool(config["tcp_enabled"]))
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1024, 65535)
        self._tcp_port.setValue(int(config["tcp_port"]))
        self._remote_start = QCheckBox("Allow third-party apps to start/stop the line")
        self._remote_start.setChecked(bool(config["allow_remote_start"]))
        self._ntp_server = QLineEdit(config.get("ntp_server", ""))
        self._ntp_server.setPlaceholderText("NTP server for trusted-time drift check (optional)")
        tcp_form = QFormLayout()
        tcp_form.addRow(self._tcp_enabled)
        tcp_form.addRow("Port", self._tcp_port)
        tcp_form.addRow(self._remote_start)
        tcp_form.addRow("NTP server", self._ntp_server)
        tcp_box = QGroupBox("TCP/IP (results, counters, commands)")
        tcp_box.setLayout(tcp_form)

        # --- 24V hard-wired signals ---
        self._io_backend = QComboBox()
        self._io_backend.addItem("Simulated (development)", "simulated")
        self._io_backend.addItem("Modbus TCP I/O block", "modbus")
        index = self._io_backend.findData(config["io_backend"])
        self._io_backend.setCurrentIndex(index if index >= 0 else 0)
        self._io_host = QLineEdit(config["io_host"])
        self._io_host.setPlaceholderText("I/O block IP, e.g. 192.168.0.50")
        self._io_port = QSpinBox()
        self._io_port.setRange(1, 65535)
        self._io_port.setValue(int(config["io_port"]))

        signals = config["signals"]
        self._channels: dict[str, QSpinBox] = {}
        io_form = QFormLayout()
        io_form.addRow("I/O backend", self._io_backend)
        io_form.addRow("Modbus host", self._io_host)
        io_form.addRow("Modbus port", self._io_port)
        for key, label in (
            ("ready", "READY output"), ("running", "RUNNING output"),
            ("pass_pulse", "PASS pulse output"), ("reject_pulse", "REJECT pulse output"),
            ("alarm", "ALARM output"), ("heartbeat", "HEARTBEAT output"),
        ):
            spin = QSpinBox()
            spin.setRange(0, 256)
            spin.setSpecialValueText("not wired")
            spin.setValue(int(signals.get(key, 0)))
            self._channels[key] = spin
            io_form.addRow(label, spin)
        io_box = QGroupBox("24V hard-wired signals (channel numbers)")
        io_box.setLayout(io_form)

        save = QPushButton("Save && apply")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save)
        self._status = QLabel("")
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        root.addWidget(tcp_box)
        root.addWidget(io_box)
        root.addWidget(save)
        root.addWidget(self._status)
        root.addStretch(1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._show_status()

    def current_config(self) -> dict:
        signals = dict(DEFAULTS["signals"])
        for key, spin in self._channels.items():
            signals[key] = spin.value()
        return {
            "tcp_enabled": self._tcp_enabled.isChecked(),
            "tcp_port": self._tcp_port.value(),
            "allow_remote_start": self._remote_start.isChecked(),
            "io_backend": self._io_backend.currentData(),
            "io_host": self._io_host.text().strip(),
            "io_port": self._io_port.value(),
            "ntp_server": self._ntp_server.text().strip(),
            "signals": signals,
        }

    def _save(self) -> None:
        config = self.current_config()
        self._settings.set(COMMS_KEY, config)
        if self._apply_callback is not None:
            try:
                self._apply_callback(config)
            except Exception as exc:
                self._status.setText(f"Saved, but applying failed: {exc}")
                return
        self._status.setText("Saved and applied.")
        self._show_status()

    def _show_status(self) -> None:
        if self._status_provider is None:
            return
        try:
            self._status.setText(self._status_provider())
        except Exception:
            pass
