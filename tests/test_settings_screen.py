import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vis.camera import CameraSettings, TriggerMode  # noqa: E402
from vis.hmi.settings_window import CameraSettingsWindow  # noqa: E402


def _qapp():
    return QApplication.instance() or QApplication([])


def _sharp_image():
    arr = np.zeros((80, 80, 3), dtype=np.uint8)
    arr[::2] = 255
    return arr


def test_settings_from_form_roundtrip():
    _qapp()
    win = CameraSettingsWindow(
        image_provider=lambda: None,
        settings=CameraSettings(exposure_us=3000, gain_db=2.0),
    )
    win._exposure.setValue(7500)
    win._trigger_mode.setCurrentText("encoder")
    win._trigger_source.setText("EncoderA/B")
    settings = win.settings_from_form()
    assert settings.exposure_us == 7500
    assert settings.trigger.mode is TriggerMode.ENCODER
    assert settings.trigger.source == "EncoderA/B"


def test_settings_lighting_aoi_trigger_roundtrip():
    _qapp()
    win = CameraSettingsWindow(image_provider=lambda: None, settings=CameraSettings())
    win._light_bright.setValue(60)
    win._light_strobe.setChecked(True)
    win._light_width.setValue(1500)
    win._trig_delay.setValue(120)
    win._trig_divider.setValue(8)
    win._aoi_w.setValue(1280)
    win._aoi_h.setValue(960)
    win._gamma.setValue(1.8)
    s = win.settings_from_form()
    assert s.lighting.brightness == 60 and s.lighting.strobe is True and s.lighting.strobe_width_us == 1500
    assert s.trigger.delay_us == 120 and s.trigger.divider == 8
    assert (s.sensor_roi.w, s.sensor_roi.h) == (1280, 960)
    assert s.gamma == 1.8
    # survives a serialize round-trip (persisted per station)
    assert CameraSettings.from_dict(s.to_dict()).lighting.strobe is True


def test_focus_readout_updates():
    _qapp()
    win = CameraSettingsWindow(image_provider=_sharp_image)
    win._poll()
    assert "focus:" in win._focus_label.text()
    assert "% of best" in win._focus_label.text()


def test_calibration_computes_mm_per_pixel():
    _qapp()
    win = CameraSettingsWindow(image_provider=lambda: None)
    win._cal_pixels.setValue(200)
    win._cal_mm.setValue(50.0)
    win._calibrate()
    assert win.calibration.mm_per_pixel == pytest.approx(0.25)
    assert "mm/px" in win._cal_label.text()


def test_save_persists_to_station(tmp_path):
    _qapp()
    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.stations import StationRepository
    from vis.db.users import UserService

    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng_id = users.create_user("eng", "Secret123", roles=("engineer",))
    repo = StationRepository(sf)
    sid = repo.create_station("S1", user_id=eng_id)
    cam_id = repo.add_camera(sid, "cam1", user_id=eng_id, settings=CameraSettings(exposure_us=1000))

    win = CameraSettingsWindow(
        image_provider=lambda: None,
        session_factory=sf,
        camera_db_id=cam_id,
        user_id=eng_id,
    )
    win._exposure.setValue(6000)
    win._save()
    assert repo.camera_settings(cam_id).exposure_us == 6000
    assert "Saved" in win._status.text()
