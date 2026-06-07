from __future__ import annotations

from pathlib import Path

import numpy as np

from ..engine.frame import Frame
from .device import CameraDevice, CameraInfo
from .settings import CameraSettings

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _load_image(path: Path) -> np.ndarray:
    from PIL import Image

    return np.array(Image.open(path).convert("RGB"), dtype=np.uint8)


class FileCamera(CameraDevice):
    """Replays images from a directory (sorted by name) as frames.

    Useful for offline testing, regression replays of real captured images, and
    development on machines without a camera (e.g. macOS).
    """

    def __init__(
        self,
        camera_id: str,
        directory: str | Path,
        loop: bool = False,
        settings: CameraSettings | None = None,
    ) -> None:
        super().__init__(CameraInfo(id=camera_id, interface="file"), settings)
        self.directory = Path(directory)
        self.loop = loop
        self._paths: list[Path] = []
        self._index = 0

    def _open_device(self) -> None:
        if not self.directory.is_dir():
            raise FileNotFoundError(f"not a directory: {self.directory}")
        self._paths = sorted(
            p for p in self.directory.iterdir() if p.suffix.lower() in _IMAGE_EXTS
        )
        self._index = 0

    def _close_device(self) -> None:
        self._paths = []
        self._index = 0

    def grab(self) -> Frame | None:
        if not self._paths:
            return None
        if self._index >= len(self._paths):
            if not self.loop:
                return None
            self._index = 0
        path = self._paths[self._index]
        frame_id = self._index
        self._index += 1
        return Frame(self.info.id, frame_id, _load_image(path), timestamp=float(frame_id))
