from __future__ import annotations

import numpy as np


def rotate_image(image, degrees) -> np.ndarray:
    """Rotate an image by a multiple of 90° (so sideways print reads upright)."""
    k = (int(degrees or 0) // 90) % 4
    return np.rot90(image, k) if k else np.asarray(image)
