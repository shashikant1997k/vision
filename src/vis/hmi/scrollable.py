"""Make any window scroll vertically when its content is taller than the screen.

Used everywhere so no screen can ever hide controls below the fold (the Apply
button, a form field, a table). Apply once per window — see make_scrollable().
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QWidget


def scroll_wrap(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def make_scrollable(window) -> None:
    """Wrap a QMainWindow's existing central widget in a vertical scroll area."""
    inner = window.centralWidget()
    if inner is not None:
        window.setCentralWidget(scroll_wrap(inner))
