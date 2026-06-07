from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from .image import numpy_to_qpixmap


def image_geometry(label_w, label_h, img_w, img_h):
    """Scale + letterbox offsets for a KeepAspectRatio image inside a label."""
    if img_w == 0 or img_h == 0:
        return 1.0, 0.0, 0.0
    scale = min(label_w / img_w, label_h / img_h)
    off_x = (label_w - img_w * scale) / 2
    off_y = (label_h - img_h * scale) / 2
    return scale, off_x, off_y


def display_to_image_roi(p1, p2, label_size, img_size):
    """Map a drag rectangle (label/display coords) to an image-space ROI."""
    lw, lh = label_size
    iw, ih = img_size
    scale, ox, oy = image_geometry(lw, lh, iw, ih)

    def to_img(px, py):
        x = (px - ox) / scale if scale else 0
        y = (py - oy) / scale if scale else 0
        return max(0, min(iw, x)), max(0, min(ih, y))

    x1, y1 = to_img(*p1)
    x2, y2 = to_img(*p2)
    return int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1))


class ImageRoiLabel(QLabel):
    """Displays an image and lets the user drag a rectangle to select an ROI
    (emitted in image coordinates via roiSelected)."""

    roiSelected = Signal(int, int, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#111")
        self._image = None
        self._base = None
        self._start = None
        self._cur = None

    def setImage(self, array) -> None:
        self._image = array
        self._base = numpy_to_qpixmap(array)
        self._render()

    def _render(self) -> None:
        if self._base is None:
            return
        scaled = self._base.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self._start is not None and self._cur is not None:
            _, ox, oy = image_geometry(
                self.width(), self.height(), self._image.shape[1], self._image.shape[0]
            )
            pm = QPixmap(scaled)
            painter = QPainter(pm)
            pen = QPen(QColor(40, 120, 255))
            pen.setWidth(2)
            painter.setPen(pen)
            rect = QRect(
                int(self._start[0] - ox),
                int(self._start[1] - oy),
                int(self._cur[0] - self._start[0]),
                int(self._cur[1] - self._start[1]),
            ).normalized()
            painter.drawRect(rect)
            painter.end()
            scaled = pm
        self.setPixmap(scaled)

    def mousePressEvent(self, event) -> None:
        if self._image is not None and event.button() == Qt.LeftButton:
            self._start = (event.position().x(), event.position().y())
            self._cur = self._start

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._cur = (event.position().x(), event.position().y())
            self._render()

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None and self._image is not None:
            end = (event.position().x(), event.position().y())
            roi = display_to_image_roi(
                self._start, end, (self.width(), self.height()),
                (self._image.shape[1], self._image.shape[0]),
            )
            self._start = None
            self._cur = None
            self._render()
            if roi[2] > 2 and roi[3] > 2:
                self.roiSelected.emit(*roi)
