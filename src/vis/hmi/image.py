from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage, QPixmap


def numpy_to_qpixmap(image: np.ndarray) -> QPixmap:
    """Convert an HxW(x3/4) uint8 numpy image to a QPixmap (copied, so it does
    not alias the numpy buffer)."""
    arr = np.ascontiguousarray(image)
    if arr.ndim == 2:
        h, w = arr.shape
        qimg = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
    else:
        h, w, ch = arr.shape
        if ch == 4:
            qimg = QImage(arr.data, w, h, 4 * w, QImage.Format_RGBA8888)
        else:
            qimg = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())
