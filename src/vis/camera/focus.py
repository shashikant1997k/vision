"""Focus assist — a sharpness metric for lens setup.

Uses the variance of the Laplacian: higher = sharper. The operator turns the
lens and watches the score peak. `FocusAssist` tracks the best score seen and
reports the current value as a percentage of it.
"""

from __future__ import annotations

import numpy as np


def _gray(image) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim == 3:
        return arr[..., :3].mean(axis=2)
    return arr


def focus_score(image, roi: tuple[int, int, int, int] | None = None) -> float:
    """Sharpness score (variance of the 4-neighbour Laplacian). roi = (x,y,w,h)."""
    g = _gray(image)
    if roi is not None:
        x, y, w, h = roi
        g = g[y : y + h, x : x + w]
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (
        g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    )
    return float(lap.var())


class FocusAssist:
    """Tracks the peak focus score so the live value can be shown as % of best."""

    def __init__(self) -> None:
        self.best = 0.0

    def update(self, image, roi=None) -> tuple[float, float]:
        score = focus_score(image, roi)
        self.best = max(self.best, score)
        percent = 100.0 * score / self.best if self.best > 0 else 0.0
        return score, percent
