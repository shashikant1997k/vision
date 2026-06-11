"""Hikrobot MVS driver, tested against a faithful fake SDK (the real bindings
require the camera + MVS install; the fake verifies the exact call protocol:
enumerate -> create handle -> open -> packet size -> start grabbing ->
settings node writes -> buffered grabs -> stop -> close -> destroy)."""

import numpy as np
import pytest

from vis.camera import CameraSettings, SensorROI, TriggerConfig, TriggerMode
from vis.camera.hikrobot import (
    MV_TRIGGER_MODE_OFF,
    MV_TRIGGER_MODE_ON,
    MV_TRIGGER_SOURCE_LINE0,
    MV_TRIGGER_SOURCE_SOFTWARE,
    PIXEL_MONO8,
    HikrobotCamera,
)


class FakeFrameInfo:
    def __init__(self, w, h, pixel, n):
        self.nWidth, self.nHeight, self.enPixelType, self.nFrameLen = w, h, pixel, n


class FakeFrameOut:
    def __init__(self):
        self.stFrameInfo = None
        self.pBufAddr = None


class FakeDeviceList:
    def __init__(self, n):
        self.nDeviceNum = n


class FakeCam:
    """Records every SDK call; serves frames from a queue."""

    def __init__(self, sdk):
        self._sdk = sdk
        self.calls = []
        self.nodes = {}

    def _rec(self, name, *args):
        self.calls.append((name, *args))
        return 0

    def MV_CC_CreateHandle(self, info):
        return self._rec("create", info)

    def MV_CC_OpenDevice(self, mode, switch):
        return self._rec("open")

    def MV_CC_GetOptimalPacketSize(self):
        self.calls.append(("packet_size",))
        return 8164

    def MV_CC_SetIntValue(self, node, value):
        self.nodes[node] = value
        return self._rec("set_int", node, value)

    def MV_CC_SetFloatValue(self, node, value):
        self.nodes[node] = value
        return self._rec("set_float", node, value)

    def MV_CC_SetBoolValue(self, node, value):
        self.nodes[node] = value
        return self._rec("set_bool", node, value)

    def MV_CC_SetEnumValue(self, node, value):
        self.nodes[node] = value
        return self._rec("set_enum", node, value)

    def MV_CC_SetEnumValueByString(self, node, value):
        self.nodes[node] = value
        return self._rec("set_enum_str", node, value)

    def MV_CC_SetCommandValue(self, node):
        return self._rec("command", node)

    def MV_CC_StartGrabbing(self):
        return self._rec("start_grab")

    def MV_CC_StopGrabbing(self):
        return self._rec("stop_grab")

    def MV_CC_GetImageBuffer(self, out, timeout):
        if not self._sdk.frames:
            return -1  # timeout
        w, h, pixel, payload = self._sdk.frames.pop(0)
        out.stFrameInfo = FakeFrameInfo(w, h, pixel, len(payload))
        out.pBufAddr = payload
        return 0

    def MV_CC_FreeImageBuffer(self, out):
        return self._rec("free_buffer")

    def MV_CC_CloseDevice(self):
        return self._rec("close")

    def MV_CC_DestroyHandle(self):
        return self._rec("destroy")


class FakeSDK:
    """Implements the MvsAdapter surface the driver uses."""

    def __init__(self, n_devices=1, serials=("DA001",)):
        self.n_devices = n_devices
        self.serials = list(serials)
        self.frames = []
        self.cam = None
        sdk = self

        class _MvCameraFactory:
            @staticmethod
            def MV_CC_EnumDevices(types, device_list):
                device_list.nDeviceNum = sdk.n_devices
                return 0

            def __new__(cls):
                sdk.cam = FakeCam(sdk)
                return sdk.cam

        self.MvCamera = _MvCameraFactory
        self.MV_CC_DEVICE_INFO_LIST = lambda: FakeDeviceList(0)
        self.MV_FRAME_OUT = FakeFrameOut

    def cast_device_info(self, device_list, index):
        return {"index": index}

    def device_serial(self, device_list, index):
        return self.serials[index]

    def frame_bytes(self, out):
        return out.pBufAddr


def _camera(sdk=None, **kw):
    return HikrobotCamera("cam1", sdk=sdk or FakeSDK(), **kw)


def test_open_protocol_and_packet_size():
    sdk = FakeSDK()
    cam = _camera(sdk)
    cam.open()
    names = [c[0] for c in sdk.cam.calls]
    assert names[:3] == ["create", "open", "packet_size"]
    assert sdk.cam.nodes["GevSCPSPacketSize"] == 8164
    assert "start_grab" in names
    cam.close()
    names = [c[0] for c in sdk.cam.calls]
    assert names[-3:] == ["stop_grab", "close", "destroy"]


def test_settings_mapped_to_genicam_nodes():
    sdk = FakeSDK()
    settings = CameraSettings(
        exposure_us=3500, gain_db=4.5, frame_rate=42.0,
        sensor_roi=SensorROI(x=64, y=32, w=1280, h=960),
        trigger=TriggerConfig(mode=TriggerMode.HARDWARE, delay_us=120),
    )
    cam = _camera(sdk, settings=settings)
    cam.open()
    nodes = sdk.cam.nodes
    assert nodes["ExposureAuto"] == "Off" and nodes["ExposureTime"] == 3500.0
    assert nodes["GainAuto"] == "Off" and nodes["Gain"] == 4.5
    assert nodes["AcquisitionFrameRate"] == 42.0
    assert (nodes["Width"], nodes["Height"], nodes["OffsetX"], nodes["OffsetY"]) == (1280, 960, 64, 32)
    assert nodes["TriggerMode"] == MV_TRIGGER_MODE_ON
    assert nodes["TriggerSource"] == MV_TRIGGER_SOURCE_LINE0
    assert nodes["TriggerDelay"] == 120.0


def test_continuous_and_software_trigger_modes():
    sdk = FakeSDK()
    cam = _camera(sdk)  # default settings: continuous
    cam.open()
    assert sdk.cam.nodes["TriggerMode"] == MV_TRIGGER_MODE_OFF

    cam.apply_settings(CameraSettings(trigger=TriggerConfig(mode=TriggerMode.SOFTWARE)))
    assert sdk.cam.nodes["TriggerMode"] == MV_TRIGGER_MODE_ON
    assert sdk.cam.nodes["TriggerSource"] == MV_TRIGGER_SOURCE_SOFTWARE
    cam.software_trigger()
    assert ("command", "TriggerSoftware") in sdk.cam.calls


def test_grab_converts_mono8_and_frees_buffer():
    sdk = FakeSDK()
    payload = bytes(range(256)) * 25  # 6400 = 80x80
    sdk.frames.append((80, 80, PIXEL_MONO8, payload))
    cam = _camera(sdk)
    cam.open()
    frame = cam.grab()
    assert frame is not None and frame.image.shape == (80, 80, 3)
    assert frame.image[0, 1, 0] == 1  # mono replicated across channels
    assert ("free_buffer",) in sdk.cam.calls
    assert cam.grab() is None  # queue empty -> timeout -> None


def test_select_by_serial_and_errors():
    sdk = FakeSDK(n_devices=2, serials=("DA001", "DA002"))
    cam = HikrobotCamera("cam2", serial="DA002", sdk=sdk)
    cam.open()  # selects index 1 without error
    cam.close()

    with pytest.raises(RuntimeError, match="serial"):
        HikrobotCamera("x", serial="NOPE", sdk=FakeSDK(n_devices=2, serials=("A", "B"))).open()
    with pytest.raises(RuntimeError, match="out of range"):
        HikrobotCamera("x", device_index=5, sdk=FakeSDK()).open()
    with pytest.raises(RuntimeError, match="no cameras"):
        HikrobotCamera("x", sdk=FakeSDK(n_devices=0)).open()


def test_unsupported_pixel_format_message():
    sdk = FakeSDK()
    sdk.frames.append((4, 4, 0x0110000A, b"\x00" * 32))  # e.g. Mono10 packed
    cam = _camera(sdk)
    cam.open()
    with pytest.raises(RuntimeError, match="PixelFormat"):
        cam.grab()


def test_frames_iterator_with_runner_shape():
    sdk = FakeSDK()
    for _ in range(3):
        sdk.frames.append((8, 8, PIXEL_MONO8, bytes(64)))
    cam = _camera(sdk)
    frames = list(cam.frames())
    assert len(frames) == 3
    assert all(isinstance(f.image, np.ndarray) for f in frames)


def test_factory_device_mapping(monkeypatch):
    from vis.hmi.app import _hik_device_for

    monkeypatch.delenv("VIS_HIK_MAP", raising=False)
    assert _hik_device_for("cam1") == {"device_index": 0}
    assert _hik_device_for("cam3") == {"device_index": 2}

    monkeypatch.setenv("VIS_HIK_MAP", "cam1:2, cam2=DA7654321")
    assert _hik_device_for("cam1") == {"device_index": 2}
    assert _hik_device_for("cam2") == {"serial": "DA7654321"}


def test_factory_selection_falls_back_to_sim(monkeypatch):
    from vis.hmi.app import _make_camera_factory

    monkeypatch.setenv("VIS_CAMERA", "sim")
    monkeypatch.delenv("VIS_GENTL_CTI", raising=False)
    factory, simulation = _make_camera_factory()
    assert simulation is True
