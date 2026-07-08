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


def _content_bbox(recipe, shape, margin=30):
    """Union of the recipe's region boxes (+ margin) — so the reject is shown
    zoomed to the product, not lost in empty conveyor margins."""
    h, w = shape[:2]
    if not recipe.regions:
        return None
    x0 = max(0, min(r.roi.x for r in recipe.regions) - margin)
    y0 = max(0, min(r.roi.y for r in recipe.regions) - margin)
    x1 = min(w, max(r.roi.x + r.roi.w for r in recipe.regions) + margin)
    y1 = min(h, max(r.roi.y + r.roi.h for r in recipe.regions) + margin)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return None
    return (x0, y0, x1, y1)


class ReviewWindow(QMainWindow):
    """Step through the recently rejected products — the annotated image zoomed
    to the product, plus a big red 'why' panel (read vs expected per failed
    field). A supervisor should get image + box + reason in one glance."""

    def __init__(self, failed_log, recipe, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reject review")
        self._items = failed_log.items()
        self._recipe = recipe
        self._index = len(self._items) - 1

        self._image = QLabel("No rejects")
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setMinimumSize(640, 380)
        self._image.setStyleSheet("background:#111; color:#888")
        self._why = QLabel("")
        self._why.setWordWrap(True)
        self._why.setTextFormat(Qt.RichText)
        self._why.setStyleSheet(
            "background:#fdf0f0; border:1px solid #e5b8b8; border-radius:6px; padding:8px"
        )
        self._counter = QLabel("")

        prev_btn = QPushButton("◀ Prev")
        prev_btn.setToolTip("Previous reject (Left arrow)")
        prev_btn.clicked.connect(self._prev)
        next_btn = QPushButton("Next ▶")
        next_btn.setToolTip("Next reject (Right arrow)")
        next_btn.clicked.connect(self._next)
        self._zoom_btn = QPushButton("⛶ Zoom to product")
        self._zoom_btn.setCheckable(True)
        self._zoom_btn.setChecked(True)
        self._zoom_btn.setToolTip("Show only the inspected area, enlarged")
        self._zoom_btn.toggled.connect(lambda _=None: self._show())
        bar = QHBoxLayout()
        bar.addWidget(prev_btn)
        bar.addWidget(self._counter)
        bar.addWidget(next_btn)
        bar.addWidget(self._zoom_btn)
        bar.addStretch(1)

        root = QVBoxLayout()
        root.addWidget(self._image, 1)
        root.addLayout(bar)
        root.addWidget(self._why)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._show()

    def keyPressEvent(self, event) -> None:  # arrow keys step through rejects
        if event.key() == Qt.Key_Left:
            self._prev()
        elif event.key() == Qt.Key_Right:
            self._next()
        else:
            super().keyPressEvent(event)

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
        import html

        item = self._items[self._index]
        image = item["image"]
        offset = (0, 0)
        if self._zoom_btn.isChecked():
            bb = _content_bbox(self._recipe, image.shape)
            if bb is not None:
                x0, y0, x1, y1 = bb
                image = image[y0:y1, x0:x1]
                offset = (x0, y0)
        annotated = draw_overlay(image, self._recipe, item["results"], offset=offset)
        pixmap = numpy_to_qpixmap(annotated)
        self._image.setPixmap(
            pixmap.scaled(self._image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._counter.setText(
            f"Reject {self._index + 1} / {len(self._items)}  (frame {item['frame_id']})"
        )
        rows = []
        for r in item["results"]:
            if r.passed:
                continue
            for tr in r.tool_results:
                if not tr.passed:
                    read = html.escape(_disp(tr.measured_value) or "(no read)")
                    exp = html.escape(_disp(tr.expected_value))
                    exp_part = f" &nbsp;expected&nbsp; <b>{exp}</b>" if exp else ""
                    rows.append(
                        f'<div style="color:#b91c1c; font-size:16px; margin:2px 0">'
                        f"✗ <b>{html.escape(tr.tool_id)}</b> — read <b>{read}</b>{exp_part}</div>"
                    )
        self._why.setText("".join(rows) if rows else
                          '<div style="color:#b91c1c">Product-level reject</div>')
