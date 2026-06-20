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
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    for k in ("VIS_CONFIG", "DATABASE_URL", "VIS_CAMERA", "VIS_GENTL_CTI"):
        monkeypatch.delenv(k, raising=False)


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
