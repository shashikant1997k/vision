from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Frame:
    """One acquired image plus its provenance."""

    camera_id: str
    frame_id: int
    image: np.ndarray
    timestamp: float
