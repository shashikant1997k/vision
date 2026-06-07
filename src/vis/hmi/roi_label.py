from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from .image import numpy_to_qpixmap

HANDLE = 6  # half-size of a corner handle, in display pixels


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
    """Displays an image. Drag to draw a new ROI (roiSelected). When a box is
    selected (set_selected_roi), drag its corners to resize or its body to move
    (roiAdjusted) — no need to delete and redraw."""

    roiSelected = Signal(int, int, int, int)
    roiAdjusted = Signal(int, int, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#111")
        self._image = None
        self._base = None
        self._start = None
        self._cur = None
        self._selected = None  # (x, y, w, h) in image coords
        self._adjust = None  # None | ("move",) | ("corner", i)
        self._adjust_origin = None
        self._adjust_mouse = None

    def setImage(self, array) -> None:
        self._image = array
        self._base = numpy_to_qpixmap(array)
        self._render()

    def set_selected_roi(self, roi) -> None:
        self._selected = tuple(roi) if roi is not None else None
        self._render()

    # ---- geometry helpers -------------------------------------------------
    def _geom(self):
        return image_geometry(
            self.width(), self.height(), self._image.shape[1], self._image.shape[0]
        )

    def _corners_display(self):
        scale, _, _ = self._geom()
        x, y, w, h = self._selected
        rx, ry, rw, rh = x * scale, y * scale, w * scale, h * scale
        return [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)], (rx, ry, rw, rh)

    def _render(self) -> None:
        if self._base is None:
            return
        scaled = self._base.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if self._selected is not None or (self._start and self._cur):
            _, ox, oy = self._geom()
            pm = QPixmap(scaled)
            painter = QPainter(pm)
            if self._selected is not None:
                corners, (rx, ry, rw, rh) = self._corners_display()
                pen = QPen(QColor(255, 200, 0))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(int(rx), int(ry), int(rw), int(rh))
                painter.setBrush(QColor(255, 200, 0))
                for cx, cy in corners:
                    painter.drawRect(int(cx - HANDLE), int(cy - HANDLE), HANDLE * 2, HANDLE * 2)
            if self._start and self._cur:
                pen = QPen(QColor(40, 120, 255))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                rect = QRect(
                    int(self._start[0] - ox), int(self._start[1] - oy),
                    int(self._cur[0] - self._start[0]), int(self._cur[1] - self._start[1]),
                ).normalized()
                painter.drawRect(rect)
            painter.end()
            scaled = pm
        self.setPixmap(scaled)

    # ---- mouse ------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._image is None or event.button() != Qt.LeftButton:
            return
        lx, ly = event.position().x(), event.position().y()
        if self._selected is not None:
            _, ox, oy = self._geom()
            px, py = lx - ox, ly - oy
            corners, (rx, ry, rw, rh) = self._corners_display()
            for i, (cx, cy) in enumerate(corners):
                if abs(px - cx) <= HANDLE + 2 and abs(py - cy) <= HANDLE + 2:
                    self._adjust = ("corner", i)
                    self._adjust_origin = self._selected
                    self._adjust_mouse = (lx, ly)
                    return
            if rx <= px <= rx + rw and ry <= py <= ry + rh:
                self._adjust = ("move",)
                self._adjust_origin = self._selected
                self._adjust_mouse = (lx, ly)
                return
        self._start = (lx, ly)
        self._cur = self._start

    def mouseMoveEvent(self, event) -> None:
        lx, ly = event.position().x(), event.position().y()
        if self._adjust is not None:
            scale, _, _ = self._geom()
            dx = (lx - self._adjust_mouse[0]) / scale
            dy = (ly - self._adjust_mouse[1]) / scale
            x, y, w, h = self._adjust_origin
            if self._adjust[0] == "move":
                nx, ny, nw, nh = x + dx, y + dy, w, h
            else:
                x0, y0, x1, y1 = x, y, x + w, y + h
                i = self._adjust[1]
                if i == 0:
                    x0, y0 = x0 + dx, y0 + dy
                elif i == 1:
                    x1, y0 = x1 + dx, y0 + dy
                elif i == 2:
                    x1, y1 = x1 + dx, y1 + dy
                else:
                    x0, y1 = x0 + dx, y1 + dy
                nx, ny, nw, nh = min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)
            iw, ih = self._image.shape[1], self._image.shape[0]
            nx = max(0, min(iw - 1, nx))
            ny = max(0, min(ih - 1, ny))
            self._selected = (int(nx), int(ny), int(nw), int(nh))
            self._render()
            return
        if self._start is not None:
            self._cur = (lx, ly)
            self._render()

    def mouseReleaseEvent(self, event) -> None:
        if self._adjust is not None:
            self._adjust = None
            if self._selected and self._selected[2] > 2 and self._selected[3] > 2:
                self.roiAdjusted.emit(*self._selected)
            return
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
