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


def test_harvester_camera_clear_error_without_driver():
    # harvesters is not installed in dev; opening must fail with a clear message.
    cam = HarvesterCamera("gige1", cti_path="/nonexistent/producer.cti")
    with pytest.raises(RuntimeError):
        cam.open()
