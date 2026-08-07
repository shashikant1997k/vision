import numpy as np
import pytest

from vis.camera import (
    Calibration,
    CameraManager,
    CameraSettings,
    FileCamera,
    SensorROI,
    TriggerConfig,
    TriggerMode,
)
from vis.camera.genicam import HarvesterCamera


class _Node:
    """One GenICam feature: a value, optional enum options, optional read-only."""

    def __init__(self, value, symbolics=None, writable=True):
        self._value = value
        self.symbolics = symbolics or []
        self._writable = writable

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if not self._writable:
            raise RuntimeError("read-only")
        if self.symbolics and v not in self.symbolics:
            raise ValueError(f"{v} not in {self.symbolics}")
        self._value = v


class _FakeNodeMap:
    """A Baumer VCXG-24C's I/O layout: Line0-2 in, Line3 the only output, one
    timer. LineMode/LineSource follow whichever line LineSelector points at."""

    def __init__(self, timer=True):
        self._modes = {"Line0": "Input", "Line1": "Input",
                       "Line2": "Input", "Line3": "Output"}
        self._sources = dict.fromkeys(self._modes, "Off")
        self.LineSelector = _Node("Line0", list(self._modes))
        sources = ["Off", "ExposureActive", "ReadoutActive"]
        if timer:
            sources.append("Timer1Active")
            self.TimerSelector = _Node("Timer1", ["Timer1"])
            self.TimerTriggerSource = _Node("Off", ["Off", "ExposureStart", "Line0"])
            self.TimerTriggerActivation = _Node("RisingEdge", ["RisingEdge", "FallingEdge"])
            self.TimerDelay = _Node(0.0)
            self.TimerDuration = _Node(10.0)
        self._source_options = sources

    @property
    def LineMode(self):
        return _Node(self._modes[self.LineSelector.value], ["Input", "Output"], writable=False)

    @property
    def LineSource(self):
        outer = self

        class _Bound(_Node):
            @property
            def value(self):
                return outer._sources[outer.LineSelector.value]

            @value.setter
            def value(self, v):
                if v not in outer._source_options:
                    raise ValueError(v)
                outer._sources[outer.LineSelector.value] = v

        return _Bound(None, outer._source_options)


def test_output_lines_finds_only_the_drivable_line():
    from vis.camera.genicam import _output_lines

    nm = _FakeNodeMap()
    assert _output_lines(nm) == ["Line3"]
    assert nm.LineSelector.value == "Line0"  # selector restored, not left roaming


def test_strobe_drives_the_output_line_through_the_timer():
    from vis.camera.genicam import _apply_strobe
    from vis.camera.settings import LightingConfig

    nm = _FakeNodeMap()
    _apply_strobe(nm, LightingConfig(strobe=True, strobe_delay_us=500, strobe_width_us=2000))

    nm.LineSelector.value = "Line3"
    assert nm.LineSource.value == "Timer1Active"
    assert nm.TimerTriggerSource.value == "ExposureStart"
    assert nm.TimerDelay.value == 500.0
    assert nm.TimerDuration.value == 2000.0


def test_strobe_off_stops_driving_the_light():
    from vis.camera.genicam import _apply_strobe
    from vis.camera.settings import LightingConfig

    nm = _FakeNodeMap()
    _apply_strobe(nm, LightingConfig(strobe=True, strobe_width_us=2000))
    _apply_strobe(nm, LightingConfig(strobe=False))

    nm.LineSelector.value = "Line3"
    assert nm.LineSource.value == "Off"


def test_strobe_falls_back_to_exposure_when_the_camera_has_no_timer():
    """A model without Timer1 must still light the part, not silently stay dark."""
    from vis.camera.genicam import _apply_strobe
    from vis.camera.settings import LightingConfig

    nm = _FakeNodeMap(timer=False)
    _apply_strobe(nm, LightingConfig(strobe=True, strobe_width_us=2000))

    nm.LineSelector.value = "Line3"
    assert nm.LineSource.value == "ExposureActive"


def test_strobe_channel_names_the_wired_line():
    from vis.camera.genicam import _apply_strobe
    from vis.camera.settings import LightingConfig

    nm = _FakeNodeMap()
    # an input line is a wiring mistake: it must not end up driving anything
    _apply_strobe(nm, LightingConfig(strobe=True, strobe_width_us=1000, channel="Line3"))
    nm.LineSelector.value = "Line3"
    assert nm.LineSource.value == "Timer1Active"


def test_waiting_caption_explains_a_triggered_camera(tmp_path, monkeypatch):
    """A camera armed on a hardware trigger produces no frame until the line
    moves — the operator must not read that as a hung application."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    from vis.camera.settings_store import save_settings
    from vis.hmi.main_window import _waiting_caption

    assert _waiting_caption("cam1") == "Starting camera…"      # nothing saved yet

    save_settings("cam1", CameraSettings(
        trigger=TriggerConfig(mode=TriggerMode.CONTINUOUS)))
    assert _waiting_caption("cam1") == "Starting camera…"

    save_settings("cam1", CameraSettings(
        trigger=TriggerConfig(mode=TriggerMode.HARDWARE, source="Line0")))
    caption = _waiting_caption("cam1")
    assert "Armed" in caption and "Line0" in caption
    assert "continuous" in caption          # tells them how to check it works

    save_settings("cam1", CameraSettings(
        trigger=TriggerConfig(mode=TriggerMode.SOFTWARE)))
    assert "software trigger" in _waiting_caption("cam1")


class _SlowCamera:
    """A camera that blocks for the full timeout and only rarely delivers —
    a triggered camera watching an idle line."""

    def __init__(self, deliver_every=4):
        self.calls = 0
        self._deliver_every = deliver_every

    def grab(self, timeout=None):
        import time as _t

        self.calls += 1
        _t.sleep(timeout or 0.2)               # what a real GenTL fetch() does
        if self.calls % self._deliver_every:
            return None
        return type("F", (), {"image": np.full((4, 4), self.calls, np.uint8)})()


def test_preview_grabber_never_blocks_the_caller():
    """The whole point: reading a frame must be instant, however long the
    camera takes. A blocking read on the Qt timer froze the whole window."""
    import time

    from vis.camera.preview import PreviewGrabber

    grabber = PreviewGrabber(_SlowCamera(), timeout=0.2)
    try:
        start = time.perf_counter()
        for _ in range(50):
            grabber.latest()
        elapsed = (time.perf_counter() - start) * 1000
        assert elapsed < 50, f"50 reads took {elapsed:.0f} ms — the caller is blocking"
    finally:
        grabber.stop()


def test_preview_grabber_serves_the_newest_frame_and_counts_it():
    import time

    from vis.camera.preview import PreviewGrabber

    grabber = PreviewGrabber(_SlowCamera(deliver_every=1), timeout=0.02)
    try:
        deadline = time.time() + 5
        while grabber.frame_count() < 3 and time.time() < deadline:
            time.sleep(0.02)
        assert grabber.frame_count() >= 3
        first = grabber.latest()
        assert first is not None
        seen = grabber.frame_count()

        deadline = time.time() + 5
        while grabber.frame_count() == seen and time.time() < deadline:
            time.sleep(0.02)
        # newest wins — a preview shows what the camera sees now, not a backlog
        assert grabber.latest()[0][0] > first[0][0]
    finally:
        grabber.stop()


def test_preview_grabber_survives_a_camera_that_throws():
    """A camera unplugged mid-preview must not kill the thread silently."""
    import time

    from vis.camera.preview import PreviewGrabber

    class _Broken:
        def grab(self, timeout=None):
            raise RuntimeError("device gone")

    grabber = PreviewGrabber(_Broken(), timeout=0.01)
    try:
        time.sleep(0.3)
        assert grabber.latest() is None
        assert grabber._thread.is_alive()
    finally:
        grabber.stop()
    assert not grabber._thread.is_alive()      # stop() actually joins


def test_camera_settings_roundtrip():
    settings = CameraSettings(
        exposure_us=3000,
        gain_db=2.5,
        frame_rate=60.0,
        sensor_roi=SensorROI(x=10, y=20, w=640, h=480),
        trigger=TriggerConfig(mode=TriggerMode.ENCODER, source="EncoderA/B", divider=4),
    )
    restored = CameraSettings.from_dict(settings.to_dict())
    assert restored == settings
    assert restored.trigger.mode is TriggerMode.ENCODER


def _write_images(directory, n):
    from PIL import Image

    for i in range(n):
        arr = np.full((32, 32, 3), 10 * (i + 1), dtype=np.uint8)
        Image.fromarray(arr).save(directory / f"img_{i:03d}.png")


def test_file_camera_replays_images(tmp_path):
    _write_images(tmp_path, 3)
    cam = FileCamera("cam1", tmp_path)
    frames = list(cam.frames())
    assert len(frames) == 3
    assert [f.frame_id for f in frames] == [0, 1, 2]
    assert frames[0].image.shape == (32, 32, 3)
    cam.close()


def test_file_camera_context_and_grab(tmp_path):
    _write_images(tmp_path, 2)
    with FileCamera("cam1", tmp_path) as cam:
        assert cam.is_open
        assert cam.grab() is not None
        assert cam.grab() is not None
        assert cam.grab() is None  # exhausted


def test_camera_manager_lifecycle(tmp_path):
    _write_images(tmp_path, 1)
    mgr = CameraManager()
    mgr.register(FileCamera("camA", tmp_path))
    mgr.register(FileCamera("camB", tmp_path))
    assert len(mgr) == 2 and "camA" in mgr
    with pytest.raises(ValueError):
        mgr.register(FileCamera("camA", tmp_path))
    mgr.open_all()
    assert mgr.get("camA").is_open
    mgr.close_all()
    assert not mgr.get("camA").is_open


def test_calibration():
    cal = Calibration.from_known_length(pixels=200, real_mm=50.0)
    assert cal.mm_per_pixel == pytest.approx(0.25)
    assert cal.px_to_mm(80) == pytest.approx(20.0)
    assert cal.distance_mm((0, 0), (0, 200)) == pytest.approx(50.0)
    assert Calibration.from_dict(cal.to_dict()).mm_per_pixel == pytest.approx(0.25)


def test_load_image_from_file(tmp_path):
    from PIL import Image

    from vis.camera.file_source import load_image

    arr = np.zeros((20, 30, 3), dtype=np.uint8)
    arr[:, :, 0] = 255
    Image.fromarray(arr).save(tmp_path / "p.png")
    loaded = load_image(tmp_path / "p.png")
    assert loaded.shape == (20, 30, 3) and loaded[0, 0, 0] == 255


def test_harvester_camera_clear_error_without_driver():
    # harvesters is not installed in dev; opening must fail with a clear message.
    cam = HarvesterCamera("gige1", cti_path="/nonexistent/producer.cti")
    with pytest.raises(RuntimeError):
        cam.open()
