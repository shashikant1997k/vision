from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from ..engine.frame import Frame
from .settings import CameraSettings


@dataclass
class CameraInfo:
    id: str
    vendor: str = ""
    model: str = ""
    serial: str = ""
    interface: str = ""


class CameraDevice(ABC):
    """A controllable camera: open/close, apply settings, grab frames.

    Subclasses implement _open_device/_close_device/grab (and optionally
    _on_settings to push parameters to the hardware). `frames()` makes any
    device usable as a pipeline source.
    """

    def __init__(self, info: CameraInfo, settings: CameraSettings | None = None) -> None:
        self.info = info
        self.settings = settings or CameraSettings()
        self._open = False
        self._stop_requested = False

    def request_stop(self) -> None:
        """Ask a running frames() loop to exit promptly — even a live camera
        waiting on a (hardware-triggered) frame that may never come."""
        self._stop_requested = True

    @property
    def is_open(self) -> bool:
        return self._open

    @abstractmethod
    def _open_device(self) -> None: ...

    @abstractmethod
    def _close_device(self) -> None: ...

    @abstractmethod
    def grab(self) -> Frame | None:
        """Return the next frame, or None when the source is exhausted."""

    def set_exposure_gain(self, exposure_us=None, gain_db=None) -> None:
        """Live exposure/gain change without restarting the stream. Default no-op;
        live cameras override it for a real-time settings preview."""

    def _on_settings(self, settings: CameraSettings) -> None:
        """Push settings to the hardware. Default: no-op (override per device)."""

    def open(self) -> CameraDevice:
        if not self._open:
            self._stop_requested = False
            self._open_device()
            self._open = True
            self._on_settings(self.settings)
        return self

    def close(self) -> None:
        if self._open:
            self._close_device()
            self._open = False

    def apply_settings(self, settings: CameraSettings) -> None:
        self.settings = settings
        if self._open:
            self._on_settings(settings)

    def frames(self, limit: int | None = None) -> Iterator[Frame]:
        self.open()
        self._stop_requested = False
        count = 0
        while (limit is None or count < limit) and not self._stop_requested:
            frame = self.grab()
            if frame is None:
                break  # bounded source exhausted (a file/sim reaching its end)
            yield frame
            count += 1

    def __enter__(self) -> CameraDevice:
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()
