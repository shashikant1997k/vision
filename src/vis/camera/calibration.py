from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Calibration:
    """Linear pixel <-> millimetre calibration (uniform scale).

    A fuller model (distortion, perspective) can replace this behind the same
    interface when needed.
    """

    mm_per_pixel: float = 1.0

    def px_to_mm(self, pixels: float) -> float:
        return pixels * self.mm_per_pixel

    def mm_to_px(self, mm: float) -> float:
        return mm / self.mm_per_pixel

    def distance_mm(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1]) * self.mm_per_pixel

    @classmethod
    def from_known_length(cls, pixels: float, real_mm: float) -> Calibration:
        """Calibrate from a known feature: `pixels` long measures `real_mm`."""
        if pixels <= 0:
            raise ValueError("pixels must be > 0")
        return cls(mm_per_pixel=real_mm / pixels)

    def to_dict(self) -> dict:
        return {"mm_per_pixel": self.mm_per_pixel}

    @classmethod
    def from_dict(cls, d: dict | None) -> Calibration:
        return cls(mm_per_pixel=float((d or {}).get("mm_per_pixel", 1.0)))
