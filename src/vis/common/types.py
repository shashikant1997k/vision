from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ROI:
    """A region of interest in pixel coordinates (origin top-left)."""

    x: int
    y: int
    w: int
    h: int


def crop(image, roi: ROI):
    """Crop a numpy HxW(xC) image to an ROI. Returns a view (cheap)."""
    return image[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]
