"""Persist the camera selection (VIS_CAMERA + GenTL producer path) so the app
finds the camera without having to set environment variables every launch.

Precedence: explicit environment variables always win (and are saved for next
time); otherwise the saved config is applied. Stored as JSON under the app data
dir (~/.vision-inspection/camera_config.json).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_KEYS = ("VIS_CAMERA", "VIS_GENTL_CTI", "VIS_CAMERA_INDEX", "VIS_MVS_PYTHON")


def _path() -> Path:
    d = Path.home() / ".vision-inspection"
    d.mkdir(exist_ok=True)
    return d / "camera_config.json"


def load_camera_config() -> dict:
    p = _path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_camera_config(values: dict) -> None:
    data = {k: v for k, v in values.items() if k in _KEYS and v}
    if data:
        _path().write_text(json.dumps(data, indent=2))


def apply_camera_config() -> None:
    """Make `vis-hmi` find the camera with no env vars: if VIS_* are set, persist
    them; otherwise load the saved values into the environment."""
    saved = load_camera_config()
    explicit = {k: os.environ[k] for k in _KEYS if os.environ.get(k)}
    if explicit:
        save_camera_config({**saved, **explicit})  # remember what was set
    else:
        for k, v in saved.items():
            if k in _KEYS and v:
                os.environ.setdefault(k, str(v))
