"""Persist last-applied camera settings per camera id, independent of any
station.

This is what makes exposure/gain/trigger "stick": the Settings screen saves
here on Apply, and every camera open (Settings preview, Teach, Run) loads from
here when no explicit settings are given — so a single-camera user never has to
configure a Station for their adjustments to survive.

Stored as JSON under the app data dir (~/.vision-inspection/camera_settings/).
"""

from __future__ import annotations

import json
from pathlib import Path

from .settings import CameraSettings


def _dir() -> Path:
    d = Path.home() / ".vision-inspection" / "camera_settings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(camera_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (camera_id or "camera"))


def path_for(camera_id: str) -> Path:
    return _dir() / f"{_safe(camera_id)}.json"


def save_settings(camera_id: str, settings: CameraSettings) -> None:
    path_for(camera_id).write_text(json.dumps(settings.to_dict(), indent=2))


def load_settings(camera_id: str) -> CameraSettings | None:
    """Return the saved settings for this camera, or None if none saved yet."""
    path = path_for(camera_id)
    if not path.exists():
        return None
    try:
        return CameraSettings.from_dict(json.loads(path.read_text()))
    except Exception:
        return None  # a corrupt file must never block opening the camera
