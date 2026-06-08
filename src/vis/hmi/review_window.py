from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..runtime import draw_overlay
from .image import numpy_to_qpixmap


def _disp(value) -> str:
    return "" if value is None else str(value).replace("\x1d", "<GS>")


class ReviewWindow(QMainWindow):
    """Step through the recently rejected products — annotated image + the exact
    inspections that failed (read vs expected). Standard reject-review filmstrip."""

    def __init__(self, failed_log, recipe, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reject review")
        self._items = failed_log.items()
        self._recipe = recipe
        self._index = len(self._items) - 1

        self._image = QLabel("No rejects")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(640, 400)
        self._image.setStyleSheet("background:#111")
        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._counter = QLabel("")

        prev_btn = QPushButton("◀ Prev")
        prev_btn.clicked.connect(self._prev)
        next_btn = QPushButton("Next ▶")
        next_btn.clicked.connect(self._next)
        bar = QHBoxLayout()
        bar.addWidget(prev_btn)
        bar.addWidget(self._counter)
        bar.addWidget(next_btn)
        bar.addStretch(1)

        root = QVBoxLayout()
        root.addWidget(self._image, 1)
        root.addLayout(bar)
        root.addWidget(self._info)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._show()

    def _prev(self) -> None:
        if self._items:
            self._index = (self._index - 1) % len(self._items)
            self._show()

    def _next(self) -> None:
        if self._items:
            self._index = (self._index + 1) % len(self._items)
            self._show()

    def _show(self) -> None:
        if not self._items:
            return
        item = self._items[self._index]
        annotated = draw_overlay(item["image"], self._recipe, item["results"])
        pixmap = numpy_to_qpixmap(annotated)
        self._image.setPixmap(
            pixmap.scaled(self._image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._counter.setText(f"Reject {self._index + 1} / {len(self._items)}  (frame {item['frame_id']})")
        fails = []
        for r in item["results"]:
            if r.passed:
                continue
            for tr in r.tool_results:
                if not tr.passed:
                    exp = _disp(tr.expected_value)
                    detail = f" (expected {exp!r})" if exp else ""
                    fails.append(f"{tr.tool_id}: read “{_disp(tr.measured_value) or '∅'}”{detail}")
        self._info.setText("Failed: " + ("; ".join(fails) if fails else "(product-level reject)"))
