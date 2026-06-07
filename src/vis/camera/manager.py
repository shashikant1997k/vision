from __future__ import annotations

from .device import CameraDevice


class CameraManager:
    """Manages the cameras on a station (one acquisition process per camera in
    the runtime — see docs/04). Provides lifecycle and lookup by id."""

    def __init__(self) -> None:
        self._devices: dict[str, CameraDevice] = {}

    def register(self, device: CameraDevice) -> CameraDevice:
        if device.info.id in self._devices:
            raise ValueError(f"camera {device.info.id!r} already registered")
        self._devices[device.info.id] = device
        return device

    def get(self, camera_id: str) -> CameraDevice:
        return self._devices[camera_id]

    def ids(self) -> list[str]:
        return list(self._devices)

    def open_all(self) -> None:
        for device in self._devices.values():
            device.open()

    def close_all(self) -> None:
        for device in self._devices.values():
            device.close()

    def __len__(self) -> int:
        return len(self._devices)

    def __contains__(self, camera_id: str) -> bool:
        return camera_id in self._devices
