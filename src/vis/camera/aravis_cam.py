"""Aravis GigE Vision camera driver — the macOS / cross-platform path.

Hikrobot's MVS SDK is Windows/Linux only, so on a Mac we acquire from the (GigE
Vision-compliant) camera through Aravis, the open-source GenICam/GigE-Vision
library (`brew install aravis`, Python via PyGObject — works on Apple Silicon).
Same CameraDevice interface as every other source, so the rest of the app is
unchanged. The Aravis namespace is injectable for tests.

Settings → GenICam (standard feature names, same as the MVS driver):
  exposure_us  -> ExposureAuto=Off, ExposureTime
  gain_db      -> GainAuto=Off, Gain
  frame_rate   -> AcquisitionFrameRate
  sensor_roi   -> Region (x,y,w,h); 0,0 = full sensor
  trigger      -> continuous = triggers cleared; software = TriggerSource
                  Software (+ software_trigger()); hardware/encoder = Line/source
"""

from __future__ import annotations

import numpy as np

from ..engine.frame import Frame
from .device import CameraDevice, CameraInfo
from .hikrobot import PIXEL_BGR8_PACKED, PIXEL_MONO8, PIXEL_RGB8_PACKED  # shared PFNC codes


def load_aravis():
    """Import the Aravis GObject-Introspection namespace, or raise with a clear
    install hint (Mac: `brew install aravis pygobject3`)."""
    try:
        import gi

        gi.require_version("Aravis", "0.8")
        from gi.repository import Aravis

        return Aravis
    except (ImportError, ValueError) as exc:  # pragma: no cover - depends on host
        raise RuntimeError(
            "Aravis not found. On macOS: `brew install aravis pygobject3`, then "
            "ensure PyGObject is importable (pip install pygobject). See "
            "docs/19-mac-gige-setup.md."
        ) from exc


class AravisCamera(CameraDevice):
    """One GigE Vision camera via Aravis, selected by enumeration index or id."""

    def __init__(
        self, camera_id: str, device_index: int = 0, device_id: str | None = None,
        settings=None, aravis=None, n_buffers: int = 8, grab_timeout_ms: int = 1000,
    ) -> None:
        super().__init__(
            CameraInfo(id=camera_id, vendor="GigE Vision (Aravis)", interface="GigE Vision"),
            settings,
        )
        self._arv = aravis
        self.device_index = device_index
        self.device_id = device_id
        self.n_buffers = n_buffers
        self.grab_timeout_ms = grab_timeout_ms
        self._cam = None
        self._stream = None
        self._frame_id = 0
        self._software_trigger = False

    # ---- lifecycle ---------------------------------------------------------
    def _open_device(self) -> None:
        arv = self._arv = self._arv or load_aravis()
        arv.update_device_list()
        n = arv.get_n_devices()
        if n == 0:
            raise RuntimeError("Aravis: no GigE Vision cameras found (check the network/subnet)")
        device_id = self.device_id
        if device_id is None:
            if self.device_index >= n:
                raise RuntimeError(
                    f"Aravis: device index {self.device_index} out of range ({n} found)"
                )
            device_id = arv.get_device_id(self.device_index)
        self._cam = arv.Camera.new(device_id)
        self.info.model = self._safe(lambda: self._cam.get_model_name(), "")
        self.info.serial = device_id

    def _close_device(self) -> None:
        if self._cam is not None:
            self._safe(lambda: self._cam.stop_acquisition())
        self._stream = None
        self._cam = None

    @staticmethod
    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    # ---- settings ----------------------------------------------------------
    def _on_settings(self, settings) -> None:
        cam, arv = self._cam, self._arv
        if cam is None:
            return
        was_streaming = self._stream is not None
        if was_streaming:
            self._safe(lambda: cam.stop_acquisition())
            self._stream = None

        self._safe(lambda: cam.set_exposure_time_auto(arv.Auto.OFF))
        self._safe(lambda: cam.set_exposure_time(float(settings.exposure_us)))
        self._safe(lambda: cam.set_gain_auto(arv.Auto.OFF))
        self._safe(lambda: cam.set_gain(float(settings.gain_db)))
        if settings.frame_rate:
            self._safe(lambda: cam.set_frame_rate(float(settings.frame_rate)))

        roi = settings.sensor_roi
        if roi.w and roi.h:
            self._safe(lambda: cam.set_region(int(roi.x), int(roi.y), int(roi.w), int(roi.h)))

        from .settings import TriggerMode

        trigger = settings.trigger
        self._software_trigger = trigger.mode == TriggerMode.SOFTWARE
        if trigger.mode == TriggerMode.CONTINUOUS:
            self._safe(lambda: cam.clear_triggers())
        elif trigger.mode == TriggerMode.SOFTWARE:
            self._safe(lambda: cam.set_trigger("Software"))
        else:  # hardware / encoder -> external line
            self._safe(lambda: cam.set_trigger(trigger.source or "Line0"))

        if was_streaming:
            self._begin_stream()

    # ---- acquisition --------------------------------------------------------
    def _begin_stream(self) -> None:
        cam, arv = self._cam, self._arv
        self._stream = cam.create_stream(None, None)
        payload = self._safe(lambda: cam.get_payload(), 0) or 0
        for _ in range(self.n_buffers):
            self._stream.push_buffer(arv.Buffer.new_allocate(payload))
        cam.start_acquisition()

    def open(self):  # ensure a stream is running after open()
        super().open()
        if self._cam is not None and self._stream is None:
            self._begin_stream()
        return self

    def software_trigger(self) -> None:
        if self._cam is not None and self._software_trigger:
            self._safe(lambda: self._cam.software_trigger())

    def grab(self) -> Frame | None:
        arv, stream, cam = self._arv, self._stream, self._cam
        if stream is None or cam is None:
            return None
        if self._software_trigger:
            self._safe(lambda: cam.software_trigger())
        buffer = stream.timeout_pop_buffer(self.grab_timeout_ms * 1000)
        if buffer is None:
            return None
        try:
            if buffer.get_status() != arv.BufferStatus.SUCCESS:
                return None
            image = self._to_numpy(buffer)
        finally:
            stream.push_buffer(buffer)  # recycle
        self._frame_id += 1
        return Frame(self.info.id, self._frame_id, image, timestamp=float(self._frame_id))

    @staticmethod
    def _to_numpy(buffer) -> np.ndarray:
        width = int(buffer.get_image_width())
        height = int(buffer.get_image_height())
        pixel = int(buffer.get_image_pixel_format())
        raw = buffer.get_data()
        data = np.frombuffer(bytes(raw), dtype=np.uint8)
        if pixel == PIXEL_MONO8:
            mono = data[: height * width].reshape(height, width)
            return np.stack([mono] * 3, axis=-1)
        if pixel in (PIXEL_RGB8_PACKED, PIXEL_BGR8_PACKED):
            rgb = data[: height * width * 3].reshape(height, width, 3)
            return rgb[..., ::-1].copy() if pixel == PIXEL_BGR8_PACKED else rgb.copy()
        raise RuntimeError(
            f"Aravis: unsupported pixel format 0x{pixel:08x} — set the camera's "
            "PixelFormat to Mono8 or RGB8 (arv-tool or the MVS client)."
        )
