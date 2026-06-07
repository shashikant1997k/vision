from __future__ import annotations

import os


from ..engine.frame import Frame
from .device import CameraDevice, CameraInfo
from .settings import CameraSettings, TriggerMode


def _try_set(node_map, name: str, value) -> None:
    """Set a GenICam feature node if the camera exposes it (cameras vary)."""
    try:
        getattr(node_map, name).value = value
    except Exception:
        pass


class HarvesterCamera(CameraDevice):
    """Real GigE Vision / GenICam camera via Harvester + a GenTL producer (.cti).

    This is the production driver for the Windows line PC (D-011). It is
    implemented behind the same CameraDevice interface as FileCamera, so the
    runtime/pipeline code is identical regardless of source.

    Requires `pip install '.[camera]'` and a GenTL producer; pass cti_path or
    set the VIS_GENTL_CTI env var. (GenICam producers for macOS are poor, so
    this runs for real on Windows/Linux.)
    """

    def __init__(
        self,
        camera_id: str,
        cti_path: str | None = None,
        device_index: int = 0,
        settings: CameraSettings | None = None,
        info: CameraInfo | None = None,
    ) -> None:
        super().__init__(info or CameraInfo(id=camera_id, interface="GigE Vision"), settings)
        self.cti_path = cti_path or os.environ.get("VIS_GENTL_CTI")
        self.device_index = device_index
        self._harvester = None
        self._acquirer = None
        self._count = 0

    def _make_harvester(self):
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
        return harvester

    def _open_device(self) -> None:
        self._harvester = self._make_harvester()
        self._acquirer = self._harvester.create(self.device_index)
        self._count = 0

    def _close_device(self) -> None:
        if self._acquirer is not None:
            try:
                self._acquirer.stop()
            except Exception:
                pass
            self._acquirer.destroy()
            self._acquirer = None
        if self._harvester is not None:
            self._harvester.reset()
            self._harvester = None

    def _on_settings(self, s: CameraSettings) -> None:
        node_map = self._acquirer.remote_device.node_map
        _try_set(node_map, "ExposureTime", float(s.exposure_us))
        _try_set(node_map, "Gain", float(s.gain_db))
        if s.frame_rate:
            _try_set(node_map, "AcquisitionFrameRate", float(s.frame_rate))
        if s.sensor_roi.w and s.sensor_roi.h:
            _try_set(node_map, "Width", int(s.sensor_roi.w))
            _try_set(node_map, "Height", int(s.sensor_roi.h))
            _try_set(node_map, "OffsetX", int(s.sensor_roi.x))
            _try_set(node_map, "OffsetY", int(s.sensor_roi.y))
        if s.trigger.mode == TriggerMode.CONTINUOUS:
            _try_set(node_map, "TriggerMode", "Off")
        else:
            _try_set(node_map, "TriggerMode", "On")
            if s.trigger.source:
                _try_set(node_map, "TriggerSource", s.trigger.source)
        # start streaming once configured
        if not getattr(self._acquirer, "is_acquiring", lambda: False)():
            self._acquirer.start()

    def grab(self) -> Frame | None:
        with self._acquirer.fetch() as buffer:
            comp = buffer.payload.components[0]
            image = comp.data.reshape(comp.height, comp.width).copy()  # mono; color TODO
        frame_id = self._count
        self._count += 1
        return Frame(self.info.id, frame_id, image, timestamp=float(frame_id))
