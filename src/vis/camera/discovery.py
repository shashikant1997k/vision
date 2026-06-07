"""Camera discovery / enumeration.

Lists the cameras available to the system. On the line PC, HarvesterDiscovery
enumerates GigE Vision / GenICam devices via a GenTL producer; in dev/tests
StaticDiscovery returns a fixed list.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from .device import CameraInfo


class CameraDiscovery(ABC):
    @abstractmethod
    def discover(self) -> list[CameraInfo]: ...


class StaticDiscovery(CameraDiscovery):
    """Returns a configured list — for dev, tests, and file/sim deployments."""

    def __init__(self, cameras: list[CameraInfo]) -> None:
        self._cameras = list(cameras)

    def discover(self) -> list[CameraInfo]:
        return list(self._cameras)


class HarvesterDiscovery(CameraDiscovery):
    """Enumerate GigE Vision / GenICam devices via Harvester + a GenTL producer
    (real, on the line PC). Needs `.[camera]` and a `.cti` producer."""

    def __init__(self, cti_path: str | None = None) -> None:
        self.cti_path = cti_path or os.environ.get("VIS_GENTL_CTI")

    def discover(self) -> list[CameraInfo]:
        try:
            from harvesters.core import Harvester
        except ImportError as exc:
            raise RuntimeError(
                "harvesters not installed. Install it with: pip install '.[camera]'"
            ) from exc
        if not self.cti_path:
            raise RuntimeError(
                "no GenTL producer (.cti) configured; pass cti_path or set VIS_GENTL_CTI"
            )
        harvester = Harvester()
        harvester.add_file(self.cti_path)
        harvester.update()
        infos: list[CameraInfo] = []
        for d in harvester.device_info_list:
            serial = getattr(d, "serial_number", "") or ""
            infos.append(
                CameraInfo(
                    id=getattr(d, "id_", "") or serial,
                    vendor=getattr(d, "vendor", "") or "",
                    model=getattr(d, "model", "") or "",
                    serial=serial,
                    interface="GigE Vision",
                )
            )
        harvester.reset()
        return infos
