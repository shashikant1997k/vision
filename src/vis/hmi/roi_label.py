from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from .image import numpy_to_qpixmap

HANDLE = 6  # half-size of a corner handle, in display pixels
MAX_ZOOM = 10.0


def image_geometry(label_w, label_h, img_w, img_h):
    """Scale + letterbox offsets for a KeepAspectRatio image inside a label
    (zoom = 1). Used by display_to_image_roi and tests."""
    if img_w == 0 or img_h == 0:
        return 1.0, 0.0, 0.0
    scale = min(label_w / img_w, label_h / img_h)
    off_x = (label_w - img_w * scale) / 2
    off_y = (label_h - img_h * scale) / 2
    return scale, off_x, off_y


def display_to_image_roi(p1, p2, label_size, img_size):
    """Map a drag rectangle (label/display coords) to an image-space ROI (zoom=1)."""
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
    """Displays an image with ZOOM (wheel) + PAN (right-drag) so operators can
    draw precise ROIs on small print in a high-resolution photo. Drag (left) to
    draw a new ROI; when a box is selected, drag its corners to resize or its
    body to move."""

    roiSelected = Signal(int, int, int, int)
    roiAdjusted = Signal(int, int, int, int)
    zoomChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 320)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#111")
        self.setMouseTracking(True)
        self._image = None
        self._base = None
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._start = None
        self._cur = None
        self._selected = None  # (x, y, w, h) in image coords
        self._adjust = None  # None | ("move",) | ("corner", i)
        self._adjust_origin = None
        self._adjust_mouse = None
        self._panning = None  # (start_lx, start_ly, start_pan_x, start_pan_y)

    def setImage(self, array) -> None:
        new_shape = None if array is None else array.shape
        prev_shape = None if self._image is None else self._image.shape
        self._image = array
        self._base = numpy_to_qpixmap(array)
        if new_shape != prev_shape:  # different image -> reset the view
            self._zoom, self._pan_x, self._pan_y = 1.0, 0.0, 0.0
        self._render()

    def set_selected_roi(self, roi) -> None:
        self._selected = tuple(roi) if roi is not None else None
        self._render()

    def reset_view(self) -> None:
        self._zoom, self._pan_x, self._pan_y = 1.0, 0.0, 0.0
        self.zoomChanged.emit(self._zoom)
        self._render()

    def zoom_by(self, factor: float) -> None:
        self._apply_zoom(factor, self.width() / 2, self.height() / 2)

    # ---- geometry ---------------------------------------------------------
    def _fit_scale(self):
        iw, ih = self._image.shape[1], self._image.shape[0]
        return min(self.width() / iw, self.height() / ih) if iw and ih else 1.0

    def _geom(self):
        """(scale, ox, oy) including zoom + pan."""
        iw, ih = self._image.shape[1], self._image.shape[0]
        scale = self._fit_scale() * self._zoom
        ox = (self.width() - iw * scale) / 2 + self._pan_x
        oy = (self.height() - ih * scale) / 2 + self._pan_y
        return scale, ox, oy

    def _clamp_pan(self):
        iw, ih = self._image.shape[1], self._image.shape[0]
        scale = self._fit_scale() * self._zoom
        base_ox = (self.width() - iw * scale) / 2
        base_oy = (self.height() - ih * scale) / 2
        self._pan_x = 0.0 if iw * scale <= self.width() else max(base_ox, min(self._pan_x, -base_ox))
        self._pan_y = 0.0 if ih * scale <= self.height() else max(base_oy, min(self._pan_y, -base_oy))

    def _to_img(self, lx, ly):
        scale, ox, oy = self._geom()
        iw, ih = self._image.shape[1], self._image.shape[0]
        x = (lx - ox) / scale if scale else 0
        y = (ly - oy) / scale if scale else 0
        return max(0, min(iw, x)), max(0, min(ih, y))

    def _apply_zoom(self, factor, cx, cy):
        if self._image is None:
            return
        ix, iy = self._to_img(cx, cy)
        self._zoom = max(1.0, min(MAX_ZOOM, self._zoom * factor))
        iw, ih = self._image.shape[1], self._image.shape[0]
        scale = self._fit_scale() * self._zoom
        base_ox = (self.width() - iw * scale) / 2
        base_oy = (self.height() - ih * scale) / 2
        self._pan_x = cx - ix * scale - base_ox  # keep (ix,iy) under the cursor
        self._pan_y = cy - iy * scale - base_oy
        self._clamp_pan()
        self.zoomChanged.emit(self._zoom)
        self._render()

    # ---- render -----------------------------------------------------------
    def _corners_display(self):
        scale, ox, oy = self._geom()
        x, y, w, h = self._selected
        rx, ry = ox + x * scale, oy + y * scale
        rw, rh = w * scale, h * scale
        return [(rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh)], (rx, ry, rw, rh)

    def _render(self):
        if self._base is None or self.width() <= 0 or self.height() <= 0:
            return
        canvas = QPixmap(self.width(), self.height())
        canvas.fill(QColor(17, 17, 17))
        scale, ox, oy = self._geom()
        iw, ih = self._image.shape[1], self._image.shape[0]
        painter = QPainter(canvas)
        # paint only the visible image region (cropped at full res then scaled)
        ix0 = max(0, int((0 - ox) / scale))
        iy0 = max(0, int((0 - oy) / scale))
        ix1 = min(iw, int((self.width() - ox) / scale) + 1)
        iy1 = min(ih, int((self.height() - oy) / scale) + 1)
        if ix1 > ix0 and iy1 > iy0:
            sub = self._base.copy(ix0, iy0, ix1 - ix0, iy1 - iy0)
            tw = max(1, int((ix1 - ix0) * scale))
            th = max(1, int((iy1 - iy0) * scale))
            sub = sub.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(int(ox + ix0 * scale), int(oy + iy0 * scale), sub)
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
            painter.drawRect(
                QRect(
                    int(self._start[0]), int(self._start[1]),
                    int(self._cur[0] - self._start[0]), int(self._cur[1] - self._start[1]),
                ).normalized()
            )
        painter.end()
        self.setPixmap(canvas)

    # ---- input ------------------------------------------------------------
    def wheelEvent(self, event):
        if self._image is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        pos = event.position()
        self._apply_zoom(factor, pos.x(), pos.y())

    def mousePressEvent(self, event):
        if self._image is None:
            return
        lx, ly = event.position().x(), event.position().y()
        if event.button() == Qt.RightButton:  # pan
            self._panning = (lx, ly, self._pan_x, self._pan_y)
            return
        if event.button() != Qt.LeftButton:
            return
        if self._selected is not None:
            corners, (rx, ry, rw, rh) = self._corners_display()
            for i, (cx, cy) in enumerate(corners):
                if abs(lx - cx) <= HANDLE + 2 and abs(ly - cy) <= HANDLE + 2:
                    self._adjust = ("corner", i)
                    self._adjust_origin = self._selected
                    self._adjust_mouse = self._to_img(lx, ly)
                    return
            if rx <= lx <= rx + rw and ry <= ly <= ry + rh:
                self._adjust = ("move",)
                self._adjust_origin = self._selected
                self._adjust_mouse = self._to_img(lx, ly)
                return
        self._start = (lx, ly)
        self._cur = self._start

    def mouseMoveEvent(self, event):
        if self._image is None:
            return
        lx, ly = event.position().x(), event.position().y()
        if self._panning is not None:
            sx, sy, px, py = self._panning
            self._pan_x = px + (lx - sx)
            self._pan_y = py + (ly - sy)
            self._clamp_pan()
            self._render()
            return
        if self._adjust is not None:
            mx, my = self._to_img(lx, ly)
            ox_i, oy_i = self._adjust_mouse
            dx, dy = mx - ox_i, my - oy_i
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
            self._selected = (int(max(0, min(iw - 1, nx))), int(max(0, min(ih - 1, ny))), int(nw), int(nh))
            self._render()
            return
        if self._start is not None:
            self._cur = (lx, ly)
            self._render()

    def mouseReleaseEvent(self, event):
        if self._panning is not None:
            self._panning = None
            return
        if self._adjust is not None:
            self._adjust = None
            if self._selected and self._selected[2] > 2 and self._selected[3] > 2:
                self.roiAdjusted.emit(*self._selected)
            return
        if self._start is not None and self._image is not None:
            x1, y1 = self._to_img(*self._start)
            x2, y2 = self._to_img(event.position().x(), event.position().y())
            roi = (int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1)))
            self._start = None
            self._cur = None
            self._render()
            if roi[2] > 2 and roi[3] > 2:
                self.roiSelected.emit(*roi)
