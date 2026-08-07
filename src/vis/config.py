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
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """Per-user DATA: the database, reports, archived images, camera settings.

    Deliberately not the app folder — this is the material that must survive an
    upgrade, and an upgrade replaces the app folder wholesale."""
    d = Path.home() / ".vision-inspection"
    d.mkdir(exist_ok=True)
    return d


def app_dir() -> Path:
    """Where the application itself lives: the folder holding vis-hmi.exe in a
    frozen build, the project root in a source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]   # src/vis/config.py -> project root


def legacy_config_path() -> Path:
    """Where config.json used to live, before it moved beside the application."""
    return Path.home() / ".vision-inspection" / "config.json"


def config_path() -> Path:
    """The site config: beside vis-hmi.exe, or the project root when run from
    source. VIS_CONFIG overrides for a second profile or a read-only install.

    NOTE this file sits IN the application folder, so replacing that folder on an
    upgrade replaces the config too — keep a copy before upgrading. The database,
    reports and images stay in data_dir() and are unaffected."""
    p = os.environ.get("VIS_CONFIG")
    return Path(p) if p else app_dir() / "config.json"


DEFAULTS: dict = {
    "database_url": "",          # blank -> sqlite in the data dir
    "report_dir": "",            # blank -> <data dir>/reports
    "station": "",               # station name (blank = single default camera)
    "camera": {
        "source": "",            # gige | hikrobot | file | sim | "" (auto)
        "gentl_cti": "",         # path to the GenTL producer (.cti) for gige
        "index": 0,              # which discovered camera (when no device_id)
        "device_id": "",         # EXACT camera, by serial number. Survives
                                 # re-discovery order, so prefer it over index.
        "map": "",               # multi-camera: "cam1=SERIAL1,cam2=SERIAL2" or
                                 # "cam1:0,cam2:1" (indexes)
        "file_dir": "",          # image folder for source=file
        "grab_timeout_ms": 0,    # 0 = backend default (2000)
        "packet_size": 0,        # GigE GevSCPSPacketSize; 0 = leave as the camera has it.
                                 # Set 1500 when the NIC/adapter cannot pass jumbo frames.
        "packet_delay": 0,       # GigE GevSCPD inter-packet delay; raise to cure packet loss
    },
    "ocr": {
        "reader": "",            # vis_ocr (trained model) | builtin | "" (default)
        "model": "",             # explicit .onnx path; blank = search the usual places
        "detector_conf": 0.4,    # text-line detector confidence threshold
        "detector_iou": 0.45,    # detector NMS IoU
        "detector_fallback": True,  # allow the slow detector rescue on a weak read
    },
    "line": {
        # stop a production batch after N rejects in a row; 0 disables the alarm.
        # This is only the fallback — the live value comes from config.json.
        "alarm_consecutive_rejects": 5,
        "require_challenge_hours": 0,     # require a passing challenge test within N h (0 = off)
    },
    "images": {
        "policy": "fails",          # none | fails | all — which frames to archive
        "dir": "",                  # blank -> <data dir>/images
        "separate_folders": True,   # keep passes and rejects in pass/ and reject/
        "write_analysis": True,     # a .json beside each reject saying why
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


def _migrate_legacy_config(target: Path) -> None:
    """Carry a pre-move config.json over to the application folder.

    config.json used to live in the user profile. Silently ignoring the old file
    would strand a commissioned station on defaults — wrong camera, wrong I/O,
    wrong reject rules — which on a line means inspecting nothing while looking
    like it works. Copy it instead, and leave the original where it is."""
    legacy = legacy_config_path()
    if not legacy.is_file():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        log.info("moved config.json from %s to %s", legacy, target)
    except Exception as exc:      # read-only app dir, permissions, …
        log.warning("could not move %s to %s (%s); using the old location",
                    legacy, target, exc)


class AppConfig:
    def __init__(self, data: dict) -> None:
        self._d = data

    @classmethod
    def load(cls) -> "AppConfig":
        data = dict(DEFAULTS)
        path = config_path()
        explicit = bool(os.environ.get("VIS_CONFIG"))
        if not path.exists() and not explicit:
            _migrate_legacy_config(path)
        # If the copy could not be made (read-only install folder), still honour
        # the old file rather than silently commissioning the station on defaults.
        if not path.exists() and not explicit and legacy_config_path().is_file():
            path = legacy_config_path()
        if path.exists():
            try:
                data = _merge(DEFAULTS, json.loads(path.read_text()))
            except Exception:
                pass  # a corrupt config must never stop the app booting
        else:
            try:
                path.write_text(json.dumps(DEFAULTS, indent=2))  # write a starter file
            except Exception:
                pass  # read-only install dir: run on defaults rather than refuse
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

    # --- line I/O/PLC link: seeds the Comms screen on a fresh station, so a
    # plant can commission the PLC by editing config.json beside the exe and
    # never has to open the UI first. Anything saved in Comms then wins.
    def io_backend(self) -> str:
        return str(self._d.get("io", {}).get("backend", "") or "")

    def io_host(self) -> str:
        return str(self._d.get("io", {}).get("host", "") or "")

    def io_port(self) -> int:
        return int(self._d.get("io", {}).get("port", 502) or 502)

    def image_policy(self) -> str:
        """Which frames to archive: none | fails | all."""
        return str(os.environ.get("VIS_IMAGE_POLICY")
                   or self._d.get("images", {}).get("policy", "fails"))

    def image_dir(self) -> str:
        return (os.environ.get("VIS_IMAGE_DIR")
                or self._d.get("images", {}).get("dir")
                or str(data_dir() / "images"))

    def image_separate_folders(self) -> bool:
        return bool(self._d.get("images", {}).get("separate_folders", True))

    def image_write_analysis(self) -> bool:
        return bool(self._d.get("images", {}).get("write_analysis", True))

    def camera_device_id(self) -> str:
        """Exact camera to open (serial number); blank = use index."""
        return os.environ.get("VIS_CAMERA_DEVICE_ID") or self._d.get("camera", {}).get("device_id", "")

    def camera_grab_timeout_ms(self) -> int:
        return int(os.environ.get("VIS_GRAB_TIMEOUT_MS")
                   or self._d.get("camera", {}).get("grab_timeout_ms", 0) or 0)

    def gige_packet_size(self) -> int:
        return int(os.environ.get("VIS_GIGE_PACKET_SIZE")
                   or self._d.get("camera", {}).get("packet_size", 0) or 0)

    def gige_packet_delay(self) -> int:
        return int(os.environ.get("VIS_GIGE_PACKET_DELAY")
                   or self._d.get("camera", {}).get("packet_delay", 0) or 0)

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
        if cam.get("device_id"):
            os.environ.setdefault("VIS_CAMERA_DEVICE_ID", str(cam["device_id"]))
        if cam.get("map"):
            os.environ.setdefault("VIS_HIK_MAP", str(cam["map"]))
        if cam.get("file_dir"):
            os.environ.setdefault("VIS_FILE_DIR", str(cam["file_dir"]))
        for key, env in (("grab_timeout_ms", "VIS_GRAB_TIMEOUT_MS"),
                         ("packet_size", "VIS_GIGE_PACKET_SIZE"),
                         ("packet_delay", "VIS_GIGE_PACKET_DELAY")):
            if int(cam.get(key, 0) or 0):
                os.environ.setdefault(env, str(int(cam[key])))
        ocr = self._d.get("ocr", {})
        if ocr.get("reader"):
            os.environ.setdefault("VIS_TEXT_READER", str(ocr["reader"]))
        if ocr.get("model"):
            os.environ.setdefault("VIS_OCR_MODEL", str(ocr["model"]))
        if "detector_conf" in ocr:
            os.environ.setdefault("VIS_DET_CONF", str(float(ocr["detector_conf"])))
        if "detector_iou" in ocr:
            os.environ.setdefault("VIS_DET_IOU", str(float(ocr["detector_iou"])))
        if not ocr.get("detector_fallback", True):
            os.environ.setdefault("VIS_OCR_DETECTOR_FALLBACK", "0")
