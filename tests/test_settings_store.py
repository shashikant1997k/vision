import json

from vis.camera.settings import CameraSettings, TriggerMode
from vis.camera.settings_store import load_settings, path_for, save_settings


def test_roundtrip_persists_exposure_gain_trigger(tmp_path, monkeypatch):
    # redirect the data dir to a temp home
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    s = CameraSettings(exposure_us=22000, gain_db=8.5)
    s.trigger.mode = TriggerMode.CONTINUOUS
    save_settings("cam1", s)

    loaded = load_settings("cam1")
    assert loaded is not None
    assert loaded.exposure_us == 22000
    assert loaded.gain_db == 8.5
    assert loaded.trigger.mode == TriggerMode.CONTINUOUS


def test_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_settings("never-saved") is None


def test_corrupt_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    save_settings("cam1", CameraSettings())
    path_for("cam1").write_text("{ not valid json")
    assert load_settings("cam1") is None  # tolerated, not raised
