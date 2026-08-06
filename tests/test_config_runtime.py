"""Site configuration: everything a plant needs to change without a rebuild.

A line engineer must be able to point the app at a different camera, cure packet
loss, or retune the detector by editing one file — not by asking for a new
build. These tests pin that contract.
"""

from __future__ import annotations

import json

import pytest

from vis.config import DEFAULTS, AppConfig


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch):
    """apply_environment() writes to the real os.environ — restore it so these
    tests cannot leak settings into the rest of the suite."""
    import os

    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def load(tmp_path, monkeypatch, data: dict) -> AppConfig:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("VIS_CONFIG", str(path))
    for key in ("VIS_CAMERA", "VIS_CAMERA_DEVICE_ID", "VIS_GRAB_TIMEOUT_MS",
                "VIS_GIGE_PACKET_SIZE", "VIS_GIGE_PACKET_DELAY", "VIS_HIK_MAP",
                "VIS_TEXT_READER", "VIS_OCR_MODEL", "VIS_DET_CONF", "VIS_DET_IOU",
                "VIS_FILE_DIR", "VIS_OCR_DETECTOR_FALLBACK"):
        monkeypatch.delenv(key, raising=False)
    return AppConfig.load()


# ---- the settings exist ---------------------------------------------------
@pytest.mark.parametrize("key", ["source", "gentl_cti", "index", "device_id", "map",
                                 "file_dir", "grab_timeout_ms", "packet_size", "packet_delay"])
def test_camera_settings_are_declared(key):
    assert key in DEFAULTS["camera"]


@pytest.mark.parametrize("key", ["reader", "model", "detector_conf",
                                 "detector_iou", "detector_fallback"])
def test_ocr_settings_are_declared(key):
    assert key in DEFAULTS["ocr"]


# ---- the file reaches the running app ------------------------------------
def test_camera_selection_reaches_the_environment(tmp_path, monkeypatch):
    """Selecting the exact camera is the whole point — index order changes when
    devices are re-discovered, a serial does not."""
    import os

    cfg = load(tmp_path, monkeypatch, {"camera": {
        "source": "gige", "device_id": "Baumer-VCXG-24C-700011045955",
        "grab_timeout_ms": 3000, "packet_size": 1500, "packet_delay": 8000}})
    cfg.apply_environment()
    assert os.environ["VIS_CAMERA"] == "gige"
    assert os.environ["VIS_CAMERA_DEVICE_ID"] == "Baumer-VCXG-24C-700011045955"
    assert os.environ["VIS_GRAB_TIMEOUT_MS"] == "3000"
    assert os.environ["VIS_GIGE_PACKET_SIZE"] == "1500"
    assert os.environ["VIS_GIGE_PACKET_DELAY"] == "8000"


def test_ocr_settings_reach_the_environment(tmp_path, monkeypatch):
    import os

    cfg = load(tmp_path, monkeypatch, {"ocr": {
        "reader": "vis_ocr", "detector_conf": 0.55, "detector_iou": 0.5,
        "detector_fallback": False}})
    cfg.apply_environment()
    assert os.environ["VIS_TEXT_READER"] == "vis_ocr"
    assert os.environ["VIS_DET_CONF"] == "0.55"
    assert os.environ["VIS_DET_IOU"] == "0.5"
    assert os.environ["VIS_OCR_DETECTOR_FALLBACK"] == "0"


def test_zero_tuning_values_are_left_to_auto_negotiation(tmp_path, monkeypatch):
    """0 must mean 'don't touch it', not 'set it to 0'."""
    import os

    cfg = load(tmp_path, monkeypatch, {"camera": {"packet_size": 0, "packet_delay": 0}})
    cfg.apply_environment()
    assert "VIS_GIGE_PACKET_SIZE" not in os.environ
    assert "VIS_GIGE_PACKET_DELAY" not in os.environ


def test_environment_wins_over_the_file(tmp_path, monkeypatch):
    """An operator debugging on the line overrides the file, not the reverse."""
    cfg = load(tmp_path, monkeypatch, {"camera": {"device_id": "FROM_FILE"}})
    monkeypatch.setenv("VIS_CAMERA_DEVICE_ID", "FROM_ENV")
    assert cfg.camera_device_id() == "FROM_ENV"


def test_typed_accessors_read_the_file(tmp_path, monkeypatch):
    cfg = load(tmp_path, monkeypatch, {"camera": {
        "device_id": "SER1", "grab_timeout_ms": 2500,
        "packet_size": 1500, "packet_delay": 4000}})
    assert cfg.camera_device_id() == "SER1"
    assert cfg.camera_grab_timeout_ms() == 2500
    assert cfg.gige_packet_size() == 1500
    assert cfg.gige_packet_delay() == 4000


def test_missing_sections_fall_back_to_defaults(tmp_path, monkeypatch):
    cfg = load(tmp_path, monkeypatch, {})
    assert cfg.camera_device_id() == ""
    assert cfg.gige_packet_size() == 0
    cfg.apply_environment()          # must not raise


# ---- the values actually change behaviour --------------------------------
def test_packet_size_reaches_the_gige_camera(monkeypatch):
    """The Windows production path: the tuning must reach the GenICam node."""
    from vis.camera.genicam import _gige_setting

    monkeypatch.setenv("VIS_GIGE_PACKET_SIZE", "9000")
    assert _gige_setting("VIS_GIGE_PACKET_SIZE", 1500) == 9000


def test_packet_size_defaults_to_a_safe_value(monkeypatch):
    """1500 by default: a camera left on jumbo streams NOTHING on a NIC that
    cannot pass jumbo frames."""
    from vis.camera.genicam import _gige_setting

    monkeypatch.delenv("VIS_GIGE_PACKET_SIZE", raising=False)
    assert _gige_setting("VIS_GIGE_PACKET_SIZE", 1500) == 1500


def test_bad_packet_value_falls_back_instead_of_crashing(monkeypatch):
    from vis.camera.genicam import _gige_setting

    monkeypatch.setenv("VIS_GIGE_PACKET_SIZE", "not-a-number")
    assert _gige_setting("VIS_GIGE_PACKET_SIZE", 1500) == 1500


def test_configured_device_id_selects_the_camera(monkeypatch):
    from vis.hmi.app import _hik_device_for

    monkeypatch.setenv("VIS_CAMERA_DEVICE_ID", "SERIAL999")
    assert _hik_device_for("cam1") == {"serial": "SERIAL999"}


def test_per_camera_map_still_wins_for_multi_camera(monkeypatch):
    from vis.hmi.app import _hik_device_for

    monkeypatch.setenv("VIS_CAMERA_DEVICE_ID", "SERIAL999")
    monkeypatch.setenv("VIS_HIK_MAP", "cam1=AAA,cam2=BBB")
    assert _hik_device_for("cam2") == {"serial": "BBB"}


def test_detector_thresholds_are_read_from_the_environment(monkeypatch):
    from vis.tools.line_detector import _env_float

    monkeypatch.setenv("VIS_DET_CONF", "0.75")
    assert _env_float("VIS_DET_CONF", 0.4) == 0.75


def test_bad_threshold_value_falls_back_instead_of_crashing(monkeypatch):
    from vis.tools.line_detector import _env_float

    monkeypatch.setenv("VIS_DET_CONF", "not-a-number")
    assert _env_float("VIS_DET_CONF", 0.4) == 0.4
