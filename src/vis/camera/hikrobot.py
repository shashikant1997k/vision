"""Hikrobot industrial camera driver (MVS SDK / MvCameraControl).

Production driver for Hikrobot MV-C* GigE/USB3 cameras via the official MVS SDK
Python bindings (`MvCameraControl_class`, installed with MVS; samples live in
e.g. /opt/MVS/Samples/64/Python or C:\\Program Files (x86)\\MVS\\Development\\
Samples\\Python). The SDK import path can be supplied with VIS_MVS_PYTHON.

Implements the same CameraDevice interface as the simulator/Harvester/file
sources, so the rest of the system (pipeline, HMI, settings screen) is
unchanged. The SDK is injectable for tests — the full open/configure/grab/close
sequence is unit-tested against a faithful fake.

CameraSettings mapping (GenICam node names per Hikrobot's manual):
  exposure_us       -> ExposureAuto=Off, ExposureTime (float, µs)
  gain_db           -> GainAuto=Off, Gain (float, dB)
  frame_rate        -> AcquisitionFrameRateEnable, AcquisitionFrameRate
  packet_size       -> GevSCPSPacketSize (GigE; MV_CC_GetOptimalPacketSize wins)
  sensor_roi        -> Width/Height/OffsetX/OffsetY (0/0 = full sensor)
  trigger.mode      -> TriggerMode Off (continuous) / On + TriggerSource
                       (software -> Software; hardware/encoder -> Line0)
  trigger.delay_us  -> TriggerDelay
"""

from __future__ import annotations

import os
import sys

import numpy as np

from ..engine.frame import Frame
from .device import CameraDevice, CameraInfo
from .settings import CameraSettings, TriggerMode

# MVS SDK enum values (from MvCameraControl_class / CameraParams_header)
MV_GIGE_DEVICE = 0x00000001
MV_USB_DEVICE = 0x00000004
MV_ACCESS_EXCLUSIVE = 1
MV_TRIGGER_MODE_OFF = 0
MV_TRIGGER_MODE_ON = 1
MV_TRIGGER_SOURCE_LINE0 = 0
MV_TRIGGER_SOURCE_SOFTWARE = 7

# GigE Vision pixel formats we convert without the SDK's converter
PIXEL_MONO8 = 0x01080001
PIXEL_RGB8_PACKED = 0x02180014
PIXEL_BGR8_PACKED = 0x02180015


class MvsAdapter:
    """Thin wrapper over the raw MVS bindings: hides the ctypes casting the raw
    structs require, so the driver (and its tests) talk to a clean surface."""

    def __init__(self, raw) -> None:
        import ctypes

        self._ct = ctypes
        self.raw = raw
        self.MvCamera = raw.MvCamera
        self.MV_CC_DEVICE_INFO_LIST = raw.MV_CC_DEVICE_INFO_LIST
        self.MV_FRAME_OUT = raw.MV_FRAME_OUT

    def cast_device_info(self, device_list, index: int):
        pointer = self._ct.cast(
            device_list.pDeviceInfo[index], self._ct.POINTER(self.raw.MV_CC_DEVICE_INFO)
        )
        return pointer.contents

    def device_serial(self, device_list, index: int) -> str:
        info = self.cast_device_info(device_list, index)
        if info.nTLayerType == MV_GIGE_DEVICE:
            chars = info.SpecialInfo.stGigEInfo.chSerialNumber
        else:
            chars = info.SpecialInfo.stUsb3VInfo.chSerialNumber
        return bytes(chars).split(b"\x00", 1)[0].decode(errors="ignore")

    def frame_bytes(self, out) -> bytes:
        return self._ct.string_at(out.pBufAddr, out.stFrameInfo.nFrameLen)


def load_sdk():
    """Import the MVS Python bindings, wrapped in MvsAdapter (raises with a
    clear installation hint). VIS_MVS_PYTHON may point at the bindings dir."""
    extra = os.environ.get("VIS_MVS_PYTHON")
    if extra and extra not in sys.path:
        sys.path.append(extra)
    try:
        import MvCameraControl_class as raw  # type: ignore

        return MvsAdapter(raw)
    except ImportError as exc:  # pragma: no cover - depends on line PC install
        raise RuntimeError(
            "Hikrobot MVS SDK not found. Install MVS (hikrobotics.com → Service → "
            "Download), then set VIS_MVS_PYTHON to the SDK's Python bindings "
            "directory (the folder containing MvCameraControl_class.py)."
        ) from exc


def _check(code, what: str) -> None:
    if code != 0:
        raise RuntimeError(f"Hikrobot SDK: {what} failed (0x{code & 0xFFFFFFFF:08x})")


class HikrobotCamera(CameraDevice):
    """One Hikrobot camera, selected by enumeration index (or serial)."""

    def __init__(
        self,
        camera_id: str,
        device_index: int = 0,
        serial: str | None = None,
        settings: CameraSettings | None = None,
        sdk=None,  # injectable for tests
        grab_timeout_ms: int = 1000,
    ) -> None:
        super().__init__(
            CameraInfo(id=camera_id, vendor="Hikrobot", interface="GigE Vision"), settings
        )
        self._sdk = sdk
        self.device_index = device_index
        self.serial = serial
        self.grab_timeout_ms = grab_timeout_ms
        self._cam = None
        self._frame_id = 0
        self._grabbing = False

    # ---- lifecycle ---------------------------------------------------------
    def _open_device(self) -> None:
        sdk = self._sdk = self._sdk or load_sdk()
        device_list = sdk.MV_CC_DEVICE_INFO_LIST()
        _check(
            sdk.MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list),
            "enumerate devices",
        )
        if device_list.nDeviceNum == 0:
            raise RuntimeError("Hikrobot SDK: no cameras found on the network/bus")
        index = self._select_index(sdk, device_list)
        self._cam = sdk.MvCamera()
        info = sdk.cast_device_info(device_list, index)
        _check(self._cam.MV_CC_CreateHandle(info), "create handle")
        _check(self._cam.MV_CC_OpenDevice(MV_ACCESS_EXCLUSIVE, 0), "open device")
        # GigE: negotiate the optimal packet size (jumbo frames when possible)
        try:
            packet = self._cam.MV_CC_GetOptimalPacketSize()
            if isinstance(packet, int) and packet > 0:
                self._cam.MV_CC_SetIntValue("GevSCPSPacketSize", packet)
        except Exception:
            pass  # USB3 devices have no GigE packet size
        _check(self._cam.MV_CC_StartGrabbing(), "start grabbing")
        self._grabbing = True

    def _select_index(self, sdk, device_list) -> int:
        if self.serial:
            for i in range(device_list.nDeviceNum):
                if sdk.device_serial(device_list, i) == self.serial:
                    return i
            raise RuntimeError(f"Hikrobot SDK: no camera with serial {self.serial!r}")
        if self.device_index >= device_list.nDeviceNum:
            raise RuntimeError(
                f"Hikrobot SDK: device index {self.device_index} out of range "
                f"({device_list.nDeviceNum} camera(s) found)"
            )
        return self.device_index

    def _close_device(self) -> None:
        if self._cam is not None:
            if self._grabbing:
                self._cam.MV_CC_StopGrabbing()
                self._grabbing = False
            self._cam.MV_CC_CloseDevice()
            self._cam.MV_CC_DestroyHandle()
            self._cam = None

    # ---- settings ----------------------------------------------------------
    def _on_settings(self, settings: CameraSettings) -> None:
        cam = self._cam
        if cam is None:
            return
        restart = self._grabbing
        if restart:  # ROI/trigger nodes are locked while grabbing
            cam.MV_CC_StopGrabbing()
            self._grabbing = False

        cam.MV_CC_SetEnumValueByString("ExposureAuto", "Off")
        cam.MV_CC_SetFloatValue("ExposureTime", float(settings.exposure_us))
        cam.MV_CC_SetEnumValueByString("GainAuto", "Off")
        cam.MV_CC_SetFloatValue("Gain", float(settings.gain_db))
        cam.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
        cam.MV_CC_SetFloatValue("AcquisitionFrameRate", float(settings.frame_rate))

        roi = settings.sensor_roi
        if roi.w and roi.h:
            cam.MV_CC_SetIntValue("Width", int(roi.w))
            cam.MV_CC_SetIntValue("Height", int(roi.h))
            cam.MV_CC_SetIntValue("OffsetX", int(roi.x))
            cam.MV_CC_SetIntValue("OffsetY", int(roi.y))

        trigger = settings.trigger
        if trigger.mode == TriggerMode.CONTINUOUS:
            cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_OFF)
        else:
            cam.MV_CC_SetEnumValue("TriggerMode", MV_TRIGGER_MODE_ON)
            source = (
                MV_TRIGGER_SOURCE_SOFTWARE
                if trigger.mode == TriggerMode.SOFTWARE
                else MV_TRIGGER_SOURCE_LINE0  # hardware + encoder arrive on Line0
            )
            cam.MV_CC_SetEnumValue("TriggerSource", source)
            if trigger.delay_us:
                cam.MV_CC_SetFloatValue("TriggerDelay", float(trigger.delay_us))

        if restart:
            _check(cam.MV_CC_StartGrabbing(), "restart grabbing")
            self._grabbing = True

    def software_trigger(self) -> None:
        """Fire one software trigger (TriggerMode=On, TriggerSource=Software)."""
        if self._cam is not None:
            self._cam.MV_CC_SetCommandValue("TriggerSoftware")

    # ---- acquisition --------------------------------------------------------
    def grab(self) -> Frame | None:
        sdk, cam = self._sdk, self._cam
        if cam is None:
            return None
        out = sdk.MV_FRAME_OUT()
        code = cam.MV_CC_GetImageBuffer(out, self.grab_timeout_ms)
        if code != 0:
            return None  # timeout (e.g. waiting for a hardware trigger)
        try:
            image = self._to_numpy(sdk, out)
        finally:
            cam.MV_CC_FreeImageBuffer(out)
        self._frame_id += 1
        return Frame(self.info.id, self._frame_id, image, timestamp=float(self._frame_id))

    @staticmethod
    def _to_numpy(sdk, out) -> np.ndarray:
        info = out.stFrameInfo
        height, width = int(info.nHeight), int(info.nWidth)
        pixel = int(info.enPixelType)
        buf = sdk.frame_bytes(out)
        data = np.frombuffer(buf, dtype=np.uint8)
        if pixel == PIXEL_MONO8:
            mono = data[: height * width].reshape(height, width)
            return np.stack([mono] * 3, axis=-1)
        if pixel in (PIXEL_RGB8_PACKED, PIXEL_BGR8_PACKED):
            rgb = data[: height * width * 3].reshape(height, width, 3)
            return rgb[..., ::-1].copy() if pixel == PIXEL_BGR8_PACKED else rgb.copy()
        raise RuntimeError(
            f"Hikrobot: unsupported pixel format 0x{pixel:08x} — set the camera's "
            "PixelFormat to Mono8 or RGB8 (MVS client → Image Format Control)."
        )
