import json
import os

import pytest

from vis.config import AppConfig, config_path


@pytest.fixture(autouse=True)
def _restore_env():
    # apply_environment() writes os.environ directly (not via monkeypatch); snapshot
    # and restore so these tests can't leak camera/DB env into other test files.
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def _home(tmp_path, monkeypatch):
    """Isolate BOTH locations: the data dir (home) and the app dir, which is
    where config.json now lives."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    monkeypatch.setattr("vis.config.app_dir", lambda: app)
    for k in ("VIS_CONFIG", "DATABASE_URL", "VIS_CAMERA", "VIS_GENTL_CTI"):
        monkeypatch.delenv(k, raising=False)
    return app


def test_config_lives_beside_the_application(tmp_path, monkeypatch):
    """config.json sits in the app folder (beside vis-hmi.exe / the project
    root), NOT in the user profile — the data dir keeps only data."""
    app = _home(tmp_path, monkeypatch)
    assert config_path() == app / "config.json"

    AppConfig.load()
    assert (app / "config.json").exists()
    assert not (tmp_path / ".vision-inspection" / "config.json").exists()


def test_legacy_config_is_carried_over_not_stranded(tmp_path, monkeypatch):
    """A station commissioned before the move must keep its settings, or it
    silently comes up on defaults with the wrong camera and I/O."""
    app = _home(tmp_path, monkeypatch)
    legacy = tmp_path / ".vision-inspection"
    legacy.mkdir(exist_ok=True)
    (legacy / "config.json").write_text(json.dumps({
        "station": "Line 3",
        "camera": {"source": "gige", "device_id": "700011045954"},
        "line": {"alarm_consecutive_rejects": 7},
    }))

    cfg = AppConfig.load()
    assert cfg.alarm_consecutive_rejects() == 7        # settings survived
    assert cfg.station() == "Line 3"
    assert (app / "config.json").exists()              # and now live beside the app
    assert (legacy / "config.json").exists()           # original left in place


def test_explicit_vis_config_wins_over_both(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    explicit = tmp_path / "elsewhere.json"
    explicit.write_text(json.dumps({"line": {"alarm_consecutive_rejects": 11}}))
    monkeypatch.setenv("VIS_CONFIG", str(explicit))

    assert config_path() == explicit
    assert AppConfig.load().alarm_consecutive_rejects() == 11


def test_io_block_seeds_the_plc_link(tmp_path, monkeypatch):
    """config.json's `io` block must actually reach the PLC screen. It used to
    be dead text: the address was set in the file and silently ignored, and the
    PLC screen talked to the simulator instead."""
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = _home(tmp_path, monkeypatch)
    (app / "config.json").write_text(json.dumps({
        "io": {"backend": "modbus", "host": "192.168.1.165", "port": 502},
    }))

    cfg = AppConfig.load()
    assert (cfg.io_backend(), cfg.io_host(), cfg.io_port()) == ("modbus", "192.168.1.165", 502)

    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.hmi.comms_window import load_comms_config

    engine = make_engine(f"sqlite:///{tmp_path}/comms.db")
    init_db(engine)
    sf = make_session_factory(engine)

    comms = load_comms_config(sf)
    assert comms["io_backend"] == "modbus"
    assert comms["io_host"] == "192.168.1.165" and comms["io_port"] == 502

    # anything saved in the Comms screen still wins over the file
    from vis.db.app_settings import SettingsService

    SettingsService(sf).set("comms", {"io_backend": "simulated", "io_host": ""})
    assert load_comms_config(sf)["io_backend"] == "simulated"


def test_defaults_write_starter_and_paths(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    cfg = AppConfig.load()
    assert config_path().exists()  # starter file written on first load
    assert cfg.database_url().startswith("sqlite:///")
    assert cfg.report_dir().endswith("reports")
    assert cfg.alarm_consecutive_rejects() == 5
    assert cfg.require_challenge_hours() == 0


def test_file_values_and_env_override(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    config_path().write_text(json.dumps({
        "line": {"alarm_consecutive_rejects": 9},
        "camera": {"source": "gige", "gentl_cti": "X.cti"},
    }))
    cfg = AppConfig.load()
    assert cfg.alarm_consecutive_rejects() == 9

    monkeypatch.setenv("DATABASE_URL", "sqlite:///explicit.db")
    assert cfg.database_url() == "sqlite:///explicit.db"  # env wins over file

    cfg.apply_environment()  # camera settings pushed to env from the file
    assert os.environ["VIS_CAMERA"] == "gige"
    assert os.environ["VIS_GENTL_CTI"] == "X.cti"


def test_corrupt_file_falls_back_to_defaults(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    config_path().write_text("{ not valid json")
    cfg = AppConfig.load()
    assert cfg.alarm_consecutive_rejects() == 5  # tolerated, not raised
