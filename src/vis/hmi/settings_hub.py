"""One tabbed Settings screen (CodeScan-style).

Hosts the individual configuration screens — Camera, Comms, PLC parameters,
Station — as tabs of a single window, instead of separate menu items. Each tab
is an existing config QMainWindow's central widget; the hub keeps the windows so
their own teardown (camera release, etc.) runs when the Settings screen closes.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QScrollArea, QTabWidget

from .scrollable import scroll_wrap


class SettingsHubWindow(QMainWindow):
    def __init__(self, tabs, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._subwindows: list = []
        tabw = QTabWidget()
        tabw.setDocumentMode(True)
        for label, win in tabs:
            if win is None:
                continue
            central = win.centralWidget() if hasattr(win, "centralWidget") else win
            if central is None:
                central = win
            # each tab scrolls on its own so the tab bar stays fixed
            content = central if isinstance(central, QScrollArea) else scroll_wrap(central)
            tabw.addTab(content, label)
            self._subwindows.append(win)
        self.setCentralWidget(tabw)

    def closeEvent(self, event) -> None:
        for win in self._subwindows:
            try:
                win.close()  # fire each screen's own teardown (camera release, timers)
            except Exception:
                pass
        super().closeEvent(event)
