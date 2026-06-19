"""Aravis GigE driver, tested against a faithful fake Aravis namespace (the real
gi/Aravis bindings need the lib + a camera; the fake verifies the call protocol:
update list -> Camera.new -> settings -> create_stream/push/start -> pop/convert/
recycle -> stop)."""

import numpy as np
import pytest

from vis.camera import CameraSettings, SensorROI, TriggerConfig, TriggerMode
from vis.camera.aravis_cam import AravisCamera
from vis.camera.hikrobot import PIXEL_MONO8


class _Auto:
    OFF = "off"


class _BufStatus:
    SUCCESS = 0


class _Buffer:
    def __init__(self, w, h, pixel, payload):
        self._w, self._h, self._pixel, self._data = w, h, pixel, payload

    def get_status(self):
        return _BufStatus.SUCCESS

    def get_image_width(self):
        return self._w

    def get_image_height(self):
        return self._h

    def get_image_pixel_format(self):
        return self._pixel

    def get_data(self):
        return self._data


class _Stream:
    def __init__(self, sdk):
        self._sdk = sdk
        self.pushed = 0

    def push_buffer(self, b):
        self.pushed += 1

    def timeout_pop_buffer(self, timeout_us):
        return self._sdk.frames.pop(0) if self._sdk.frames else None


class _Camera:
    def __init__(self, sdk, device_id):
        self._sdk = sdk
        self.device_id = device_id
        self.calls = []
        self.nodes = {}

    def get_model_name(self):
        return "MV-CA-FAKE"

    def set_exposure_time_auto(self, v): self.nodes["ExposureAuto"] = v
    def set_exposure_time(self, v): self.nodes["ExposureTime"] = v
    def set_gain_auto(self, v): self.nodes["GainAuto"] = v
    def set_gain(self, v): self.nodes["Gain"] = v
    def set_frame_rate(self, v): self.nodes["AcquisitionFrameRate"] = v
    def set_region(self, x, y, w, h): self.nodes["Region"] = (x, y, w, h)
    def clear_triggers(self): self.calls.append("clear_triggers")
    def set_trigger(self, src): self.calls.append(("set_trigger", src))
    def software_trigger(self): self.calls.append("software_trigger")
    def get_payload(self): return 64

    def create_stream(self, a, b):
        self._sdk.stream = _Stream(self._sdk)
        return self._sdk.stream

    def start_acquisition(self): self.calls.append("start")
    def stop_acquisition(self): self.calls.append("stop")


class FakeAravis:
    def __init__(self, n_devices=1, ids=("fake-cam-0",)):
        self.n_devices = n_devices
        self.ids = list(ids)
        self.frames = []
        self.stream = None
        self.cam = None
        self.Auto = _Auto
        self.BufferStatus = _BufStatus
        sdk = self

        class _CameraFactory:
            @staticmethod
            def new(device_id):
                sdk.cam = _Camera(sdk, device_id)
                return sdk.cam

        class _BufferFactory:
            @staticmethod
            def new_allocate(n):
                return ("alloc", n)

        self.Camera = _CameraFactory
        self.Buffer = _BufferFactory

    def update_device_list(self): pass
    def get_n_devices(self): return self.n_devices
    def get_device_id(self, i): return self.ids[i]


def test_open_configures_and_streams():
    arv = FakeAravis()
    settings = CameraSettings(
        exposure_us=2500, gain_db=3.0, frame_rate=40.0,
        sensor_roi=SensorROI(0, 0, 640, 480),
        trigger=TriggerConfig(mode=TriggerMode.CONTINUOUS),
    )
    cam = AravisCamera("cam1", settings=settings, aravis=arv).open()
    assert arv.cam.nodes["ExposureAuto"] == "off" and arv.cam.nodes["ExposureTime"] == 2500.0
    assert arv.cam.nodes["Gain"] == 3.0 and arv.cam.nodes["AcquisitionFrameRate"] == 40.0
    assert arv.cam.nodes["Region"] == (0, 0, 640, 480)
    assert "clear_triggers" in arv.cam.calls and "start" in arv.cam.calls
    assert arv.stream.pushed == cam.n_buffers
    cam.close()
    assert "stop" in arv.cam.calls


def test_software_trigger_mode():
    arv = FakeAravis()
    cam = AravisCamera("cam1", aravis=arv,
                       settings=CameraSettings(trigger=TriggerConfig(mode=TriggerMode.SOFTWARE))).open()
    assert ("set_trigger", "Software") in arv.cam.calls
    arv.frames.append(_Buffer(8, 8, PIXEL_MONO8, bytes(64)))
    cam.grab()
    assert "software_trigger" in arv.cam.calls  # fired before pop


def test_hardware_trigger_uses_line():
    arv = FakeAravis()
    AravisCamera("cam1", aravis=arv,
                 settings=CameraSettings(trigger=TriggerConfig(mode=TriggerMode.HARDWARE,
                                                               source="Line1"))).open()
    assert ("set_trigger", "Line1") in arv.cam.calls


def test_grab_converts_mono8_and_recycles():
    arv = FakeAravis()
    cam = AravisCamera("cam1", aravis=arv).open()
    payload = bytes(range(64))  # 8x8 mono
    arv.frames.append(_Buffer(8, 8, PIXEL_MONO8, payload))
    frame = cam.grab()
    assert frame is not None and frame.image.shape == (8, 8, 3)
    assert frame.image[0, 1, 0] == 1
    assert cam.grab() is None  # no buffer -> timeout -> None


def test_device_selection_errors():
    with pytest.raises(RuntimeError, match="no GigE"):
        AravisCamera("x", aravis=FakeAravis(n_devices=0)).open()
    with pytest.raises(RuntimeError, match="out of range"):
        AravisCamera("x", device_index=5, aravis=FakeAravis(n_devices=1)).open()


def test_unsupported_pixel_format():
    arv = FakeAravis()
    cam = AravisCamera("cam1", aravis=arv).open()
    arv.frames.append(_Buffer(4, 4, 0x0110000A, bytes(32)))  # Mono10 packed
    with pytest.raises(RuntimeError, match="PixelFormat"):
        cam.grab()


def test_frames_iterator():
    arv = FakeAravis()
    cam = AravisCamera("cam1", aravis=arv).open()
    for _ in range(3):
        arv.frames.append(_Buffer(8, 8, PIXEL_MONO8, bytes(64)))
    frames = list(cam.frames())
    assert len(frames) == 3 and all(isinstance(f.image, np.ndarray) for f in frames)
