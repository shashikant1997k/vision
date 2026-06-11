from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.app_settings import EventService

_COLORS = {"alarm": QColor(200, 30, 30), "warn": QColor(180, 120, 0)}


class EventsWindow(QMainWindow):
    """Operational event/alarm log — run/stop, alarms raised and cleared, batch
    open/close. Append-only (distinct from the Part-11 audit trail)."""

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Events & alarms")
        self._events = EventService(session_factory)

        self._severity = QComboBox()
        self._severity.addItem("All", None)
        for label in ("alarm", "warn", "info"):
            self._severity.addItem(label, label)
        self._severity.currentIndexChanged.connect(self._refresh)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Severity"))
        bar.addWidget(self._severity)
        bar.addWidget(refresh)
        bar.addStretch(1)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Time", "Severity", "Source", "Message"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)

        root = QVBoxLayout()
        root.addLayout(bar)
        root.addWidget(self._table, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._refresh()

    def _refresh(self) -> None:
        rows = self._events.list_events(severity=self._severity.currentData())
        self._table.setRowCount(len(rows))
        for r, event in enumerate(rows):
            for c, value in enumerate(
                (event["ts"][:19], event["severity"].upper(), event["source"], event["message"])
            ):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                color = _COLORS.get(event["severity"])
                if color is not None:
                    item.setForeground(color)
                self._table.setItem(r, c, item)
