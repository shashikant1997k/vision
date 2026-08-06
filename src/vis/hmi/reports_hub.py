"""One Reports screen — everything you'd look up *after* a run, in one place.

Batch records, reject images, the event log and the audit trail were reachable
from four different buttons (two of them buried in Admin). They answer the same
kind of question — "what happened, and can I prove it?" — so they belong on one
screen with tabs, the way Settings already works.

Tabs are built lazily: opening Reports must not query the whole database, and a
tab that cannot be built (no rejects captured yet, no permission for the audit
trail) simply isn't offered rather than showing a broken page.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QLabel, QMainWindow, QScrollArea, QTabWidget

from .scrollable import scroll_wrap

log = logging.getLogger(__name__)


class ReportsHubWindow(QMainWindow):
    """Hosts the reporting screens as tabs of a single window.

    ``tabs`` is a sequence of ``(label, factory)``; each factory returns a
    QMainWindow/QWidget and is called once, when its tab is first shown.
    """

    def __init__(self, tabs, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reports")
        self._factories: dict[int, callable] = {}
        self._subwindows: list = []
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        for label, factory in tabs:
            if factory is None:
                continue
            index = self._tabs.addTab(QLabel("Loading…"), label)
            self._factories[index] = factory
        self._tabs.currentChanged.connect(self._ensure_tab)
        self.setCentralWidget(self._tabs)
        if self._tabs.count():
            self._ensure_tab(self._tabs.currentIndex())

    def _ensure_tab(self, index: int) -> None:
        factory = self._factories.pop(index, None)
        if factory is None:
            return
        try:
            window = factory()
        except Exception as exc:  # a broken report must not take down the screen
            log.exception("could not build the %r report", self._tabs.tabText(index))
            message = QLabel(f"This report could not be opened.\n\n{exc}")
            message.setWordWrap(True)
            message.setContentsMargins(24, 24, 24, 24)
            self._tabs.removeTab(index)
            self._tabs.insertTab(index, message, self._tabs.tabText(index))
            self._tabs.setCurrentIndex(index)
            return
        central = window.centralWidget() if hasattr(window, "centralWidget") else window
        if central is None:
            central = window
        content = central if isinstance(central, QScrollArea) else scroll_wrap(central)
        label = self._tabs.tabText(index)
        self._tabs.removeTab(index)
        self._tabs.insertTab(index, content, label)
        self._tabs.setCurrentIndex(index)
        self._subwindows.append(window)   # keep it alive; its teardown runs on close

    def closeEvent(self, event) -> None:
        for window in self._subwindows:
            try:
                window.close()
            except Exception:
                log.exception("error closing a report window")
        super().closeEvent(event)
