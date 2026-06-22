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
        # how long a single grab waits for a frame before giving up (and the
        # loop checks for stop / tolerates a hardware-trigger gap). Short so Stop
        # is responsive; frames() tolerates a None so gaps don't end acquisition.
        self._grab_timeout = float(os.environ.get("VIS_GRAB_TIMEOUT", "1.0"))

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
        if not os.path.exists(self.cti_path):
            raise RuntimeError(
                f"GenTL producer not found at {self.cti_path!r}; "
                "check the path / VIS_GENTL_CTI (e.g. Baumer's bgapi2_gige.cti)"
            )
        # The producer's dependent DLLs sit next to the .cti; make them
        # loadable (Windows won't search the .cti's own dir otherwise).
        bindir = os.path.dirname(self.cti_path)
        try:
            os.add_dll_directory(bindir)
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        harvester = Harvester()
        harvester.add_file(self.cti_path)
        harvester.update()
        return harvester

    def _open_device(self) -> None:
        self._harvester = self._make_harvester()
        # No camera (unplugged / wrong subnet / held by another app) leaves the
        # device list empty; harvesters then raises a bare IndexError on create.
        # Translate both that and an out-of-range index into a clear message.
        if not self._harvester.device_info_list:
            raise RuntimeError(
                "no GigE Vision cameras found via the GenTL producer; check the "
                "camera is powered, linked, and on a reachable subnet"
            )
        try:
            self._acquirer = self._harvester.create(self.device_index)
        except IndexError as exc:
            raise RuntimeError(
                f"no camera at device index {self.device_index}; "
                f"{len(self._harvester.device_info_list)} device(s) detected"
            ) from exc
        self._count = 0

    def _close_device(self) -> None:
        # Each step is independently guarded so a teardown quirk in one never
        # skips the next: some GenTL producers (Baumer) raise a BusyException
        # while revoking buffers if acquisition is still active. If destroy()
        # then threw, harvester.reset() would never run and the camera would be
        # left owned/wedged (needing a power-cycle). Stop only when acquiring,
        # and always fall through to reset().
        if self._acquirer is not None:
            try:
                if getattr(self._acquirer, "is_acquiring", lambda: False)():
                    self._acquirer.stop()
            except Exception:
                pass
            try:
                self._acquirer.destroy()
            except Exception:
                pass
            self._acquirer = None
        if self._harvester is not None:
            try:
                self._harvester.reset()
            except Exception:
                pass
            self._harvester = None

    def _on_settings(self, s: CameraSettings) -> None:
        node_map = self._acquirer.remote_device.node_map
        # Several GenICam features (packet size, AOI, pixel format) are LOCKED
        # while acquisition runs — writing them mid-stream stalls the camera and
        # hangs the caller. Always stop, apply, then restart. This is what makes
        # "Apply" in the Settings screen safe.
        was_acquiring = getattr(self._acquirer, "is_acquiring", lambda: False)()
        if was_acquiring:
            try:
                self._acquirer.stop()
            except Exception:
                pass
        # Keep the stream packet size within the NIC MTU (1500). A camera left
        # with a jumbo default streams nothing on a non-jumbo NIC.
        _try_set(node_map, "GevSCPSPacketSize", 1500)
        _try_set(node_map, "ExposureTime", float(s.exposure_us))
        _try_set(node_map, "Gain", float(s.gain_db))
        if getattr(s, "black_level", 0):
            _try_set(node_map, "BlackLevel", float(s.black_level))
        if getattr(s, "sharpness", 0):
            # node name differs by vendor; try the common ones (best-effort)
            for nm in ("Sharpness", "SharpnessEnhancement", "SharpnessAmount"):
                _try_set(node_map, nm, float(s.sharpness))
        if s.frame_rate:
            _try_set(node_map, "AcquisitionFrameRate", float(s.frame_rate))
        if s.sensor_roi.w and s.sensor_roi.h:
            _try_set(node_map, "Width", int(s.sensor_roi.w))
            _try_set(node_map, "Height", int(s.sensor_roi.h))
            _try_set(node_map, "OffsetX", int(s.sensor_roi.x))
            _try_set(node_map, "OffsetY", int(s.sensor_roi.y))
        # TriggerMode must be set per TriggerSelector; setting it blind can
        # silently no-op and leave a camera stuck waiting for a hardware pulse
        # (the VCXG-24C ships selector=FrameStart, source=Line0). For a hardware
        # trigger the sensor pulses TriggerSource (e.g. Line0) per product.
        if s.trigger.mode == TriggerMode.CONTINUOUS:
            for sel in ("FrameStart", "AcquisitionStart"):
                _try_set(node_map, "TriggerSelector", sel)
                _try_set(node_map, "TriggerMode", "Off")
        else:
            _try_set(node_map, "TriggerSelector", "FrameStart")
            _try_set(node_map, "TriggerMode", "On")
            if s.trigger.source:
                _try_set(node_map, "TriggerSource", s.trigger.source)
            if s.trigger.delay_us:
                _try_set(node_map, "TriggerDelay", float(s.trigger.delay_us))
            if getattr(s.trigger, "debounce_us", 0):
                # anti-bounce on the trigger line; node name varies by vendor
                for nm in ("LineDebouncerHighTimeAbs", "TriggerDebouncerHighTimeAbs",
                           "LineDebouncerTime"):
                    _try_set(node_map, nm, float(s.trigger.debounce_us))
        # (re)start streaming once configured
        try:
            self._acquirer.start()
        except Exception:
            pass

    def set_exposure_gain(self, exposure_us=None, gain_db=None) -> None:
        """Apply exposure/gain to the LIVE stream without stopping it — for a
        real-time settings preview (both are settable while acquiring)."""
        if self._acquirer is None:
            return
        node_map = self._acquirer.remote_device.node_map
        if exposure_us is not None:
            _try_set(node_map, "ExposureTime", float(exposure_us))
        if gain_db is not None:
            _try_set(node_map, "Gain", float(gain_db))

    def frames(self, limit: int | None = None):
        # Live camera: a missing frame means "none yet" (waiting on a trigger or
        # a transient stall), NOT end-of-stream — keep waiting instead of ending
        # acquisition. request_stop()/stop budget bounds how long we block.
        self.open()
        self._stop_requested = False
        count = 0
        while (limit is None or count < limit) and not self._stop_requested:
            frame = self.grab()
            if frame is None:
                continue
            yield frame
            count += 1

    def grab(self, timeout: float | None = None) -> Frame | None:
        t = self._grab_timeout if timeout is None else timeout
        try:
            with self._acquirer.fetch(timeout=t) as buffer:
                comp = buffer.payload.components[0]
                image = comp.data.reshape(comp.height, comp.width).copy()  # mono; color TODO
        except Exception:
            return None  # timeout / transient stall — no frame this cycle
        frame_id = self._count
        self._count += 1
        return Frame(self.info.id, frame_id, image, timestamp=float(frame_id))
