from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Iterator

import numpy as np

from ..domain.entities import Recipe
from .frame import Frame


class Camera(ABC):
    """Acquisition source. Real implementation = GenICam/Harvester (D-011);
    the fake source lets the whole pipeline run with no hardware (e.g. on Mac).
    """

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id

    @abstractmethod
    def frames(self) -> Iterator[Frame]:
        """Yield frames until the source is exhausted/stopped."""


class FakeCamera(Camera):
    """Generates synthetic frames for the walking skeleton.

    For each tool it 'prints' the expected value into the tool's top-left
    pixel, injecting a misprint at `defect_rate` so the reject path is
    exercised. Deterministic given a seed.
    """

    def __init__(
        self,
        camera_id: str,
        recipe: Recipe,
        num_frames: int = 10,
        width: int = 1280,
        height: int = 480,
        defect_rate: float = 0.2,
        seed: int = 0,
    ) -> None:
        super().__init__(camera_id)
        self.recipe = recipe
        self.num_frames = num_frames
        self.width = width
        self.height = height
        self.defect_rate = defect_rate
        self._rng = random.Random(seed)

    def frames(self) -> Iterator[Frame]:
        for i in range(self.num_frames):
            img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
            for region in self.recipe.regions:
                for tool in region.tools:
                    expected = int(tool.config.get("expected", 0))
                    value = expected
                    if self._rng.random() < self.defect_rate:
                        value = (expected + 1) % 256  # simulate a misprint
                    ax = region.roi.x + tool.roi.x
                    ay = region.roi.y + tool.roi.y
                    img[ay, ax, 0] = value
            yield Frame(self.camera_id, i, img, timestamp=float(i))
