"""Single site configuration file for install / line setup.

Industrial deployments configure the app from one file rather than scattered
env vars. This reads ``~/.vision-inspection/config.json`` (override the location
with the ``VIS_CONFIG`` env var) and exposes the install-time settings: database,
camera/GenTL producer, station identity, file paths, and line parameters
(reject alarm, challenge-test gate). Environment variables still override the
file for one-off runs; the file is the persistent setup.

A starter file with every option is written on first run if none exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def data_dir() -> Path:
    d = Path.home() / ".vision-inspection"
    d.mkdir(exist_ok=True)
    return d


def config_path() -> Path:
    p = os.environ.get("VIS_CONFIG")
    return Path(p) if p else data_dir() / "config.json"


DEFAULTS: dict = {
    "database_url": "",          # blank -> sqlite in the data dir
    "report_dir": "",            # blank -> <data dir>/reports
    "station": "",               # station name (blank = single default camera)
    "camera": {
        "source": "",            # gige | hikrobot | aravis | sim | "" (auto)
        "gentl_cti": "",         # path to the GenTL producer (.cti) for gige
        "index": 0,              # which discovered camera
    },
    "line": {
        "alarm_consecutive_rejects": 5,   # stop a production batch after N rejects in a row
        "require_challenge_hours": 0,     # require a passing challenge test within N h (0 = off)
    },
    "io": {
        "backend": "",           # "" (simulated) | modbus
        "host": "",
        "port": 502,
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class AppConfig:
    def __init__(self, data: dict) -> None:
        self._d = data

    @classmethod
    def load(cls) -> "AppConfig":
        data = dict(DEFAULTS)
        path = config_path()
        if path.exists():
            try:
                data = _merge(DEFAULTS, json.loads(path.read_text()))
            except Exception:
                pass  # a corrupt config must never stop the app booting
        else:
            try:
                path.write_text(json.dumps(DEFAULTS, indent=2))  # write a starter file
            except Exception:
                pass
        return cls(data)

    def save(self) -> None:
        config_path().write_text(json.dumps(self._d, indent=2))

    # --- typed accessors (environment variables win) -----------------------
    def database_url(self) -> str:
        return (os.environ.get("DATABASE_URL") or self._d.get("database_url")
                or f"sqlite:///{data_dir() / 'vis.db'}")

    def report_dir(self) -> str:
        return self._d.get("report_dir") or str(data_dir() / "reports")

    def station(self) -> str:
        return os.environ.get("VIS_STATION") or self._d.get("station", "")

    def alarm_consecutive_rejects(self) -> int:
        return int(self._d.get("line", {}).get("alarm_consecutive_rejects", 5) or 0)

    def require_challenge_hours(self) -> int:
        return int(self._d.get("line", {}).get("require_challenge_hours", 0) or 0)

    def apply_environment(self) -> None:
        """Push file settings into the environment so the rest of the app (which
        reads env vars) picks them up — without clobbering explicit env vars."""
        os.environ.setdefault("DATABASE_URL", self.database_url())
        cam = self._d.get("camera", {})
        if cam.get("source"):
            os.environ.setdefault("VIS_CAMERA", str(cam["source"]))
        if cam.get("gentl_cti"):
            os.environ.setdefault("VIS_GENTL_CTI", str(cam["gentl_cti"]))
        if cam.get("index"):
            os.environ.setdefault("VIS_CAMERA_INDEX", str(cam["index"]))
