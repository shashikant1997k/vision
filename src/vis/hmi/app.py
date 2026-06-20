from __future__ import annotations

import sys


def _ensure_default_admin(users) -> None:
    """First-run convenience: seed roles and a default admin (admin/admin123)."""
    users.seed_roles()
    try:
        users.create_user("admin", "admin123", full_name="Administrator", roles=("admin",))
    except Exception:
        pass  # already exists


def _sim_factory(camera_id, settings, recipe):
    from ..engine.sim import SimulatedCodeCamera

    return SimulatedCodeCamera(camera_id, recipe, num_frames=60, defect_rate=0.25, seed=0)


def _hik_device_for(camera_id: str) -> dict:
    """Map a logical camera id to a physical Hikrobot device.

    VIS_HIK_MAP="cam1:0,cam2:1" (enumeration indexes) or
    VIS_HIK_MAP="cam1=DA1234567,cam2=DA1234568" (serials). Without a map, the
    trailing digit of the id picks the index (cam1 -> 0, cam2 -> 1)."""
    import os
    import re

    mapping = os.environ.get("VIS_HIK_MAP", "")
    for entry in (e.strip() for e in mapping.split(",") if e.strip()):
        if ":" in entry:
            cid, _, idx = entry.partition(":")
            if cid.strip() == camera_id:
                return {"device_index": int(idx)}
        elif "=" in entry:
            cid, _, serial = entry.partition("=")
            if cid.strip() == camera_id:
                return {"serial": serial.strip()}
    digits = re.findall(r"(\d+)$", camera_id)
    return {"device_index": max(0, int(digits[0]) - 1) if digits else 0}


def _make_camera_factory():
    """Pick the acquisition source, best first:
    1. Hikrobot MVS SDK   (VIS_CAMERA=hikrobot, or auto when the SDK imports) — line PC
    2. Aravis GigE Vision (VIS_CAMERA=aravis, or auto when Aravis imports) — macOS/dev
    3. GenTL / Harvester  (VIS_GENTL_CTI set — any GigE Vision camera)
    4. Simulator          (development; the HMI shows a SIMULATION banner)
    Returns (factory, simulation)."""
    import os

    choice = os.environ.get("VIS_CAMERA", "auto").lower()

    def hik_available() -> bool:
        try:
            from ..camera.hikrobot import load_sdk

            load_sdk()
            return True
        except Exception:
            return False

    def aravis_available() -> bool:
        # NB: never import Aravis in the app's (venv) Python — on macOS the pip
        # PyGObject binding segfaults. Probe out-of-process and only auto-select
        # Aravis when a camera is actually connected (else fall back to the sim).
        try:
            from ..camera.aravis_proc import count_devices

            return count_devices() > 0
        except Exception:
            return False

    if choice == "hikrobot" or (choice == "auto" and hik_available()):
        def hik_factory(camera_id, settings, recipe):
            from ..camera.hikrobot import HikrobotCamera
            from ..camera.settings_store import load_settings

            settings = settings or load_settings(camera_id)
            camera = HikrobotCamera(camera_id, settings=settings, **_hik_device_for(camera_id))
            camera.open()
            return camera

        return hik_factory, False

    if choice == "aravis" or (choice == "auto" and aravis_available()):
        def aravis_factory(camera_id, settings, recipe):
            # out-of-process worker (reliable on macOS); the in-venv binding
            # segfaults, so we read frames from a brew-python worker subprocess.
            from ..camera.aravis_proc import AravisProcessCamera
            from ..camera.settings_store import load_settings

            settings = settings or load_settings(camera_id)
            dev = _hik_device_for(camera_id)  # same id->index/serial mapping
            kwargs = {"device_id": dev["serial"]} if "serial" in dev else {
                "device_index": dev.get("device_index", 0)
            }
            camera = AravisProcessCamera(camera_id, settings=settings, **kwargs)
            camera.open()
            return camera

        return aravis_factory, False

    cti = os.environ.get("VIS_GENTL_CTI")
    if choice == "gige" or (choice == "auto" and cti):
        def gige_factory(camera_id, settings, recipe):
            from ..camera.genicam import HarvesterCamera
            from ..camera.settings_store import load_settings

            index = int(os.environ.get("VIS_CAMERA_INDEX", "0"))
            settings = settings or load_settings(camera_id)
            camera = HarvesterCamera(camera_id, cti_path=cti, device_index=index, settings=settings)
            camera.open()
            return camera

        return gige_factory, False
    return _sim_factory, True


def main() -> int:
    import os
    from pathlib import Path

    # Persist to a fixed location so saved recipes survive across runs regardless
    # of the working directory (a relative sqlite file would not).
    if not os.environ.get("DATABASE_URL"):
        data_dir = Path.home() / ".vision-inspection"
        data_dir.mkdir(exist_ok=True)
        os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'vis.db'}"

    from PySide6.QtWidgets import QApplication, QDialog

    from ..cli import build_code_demo_recipe
    from ..db.base import init_db, make_engine, make_session_factory
    from ..db.users import UserService
    from .login import LoginDialog
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    from .theme import apply_theme
    from .wheel_guard import WheelGuard

    apply_theme(app)
    app._wheel_guard = WheelGuard()  # keep a ref; ignore wheel on unfocused fields
    app.installEventFilter(app._wheel_guard)

    engine = make_engine()
    init_db(engine)
    users = UserService(make_session_factory(engine))
    _ensure_default_admin(users)

    login = LoginDialog(users)
    if login.exec() != QDialog.Accepted:
        return 0

    sf = make_session_factory(engine)

    # seed the built-in OCV starter fonts (idempotent)
    from ..db.fonts import FontRepository

    try:
        FontRepository(sf).ensure_builtins()
    except Exception:
        pass  # font seeding must never block startup

    # Part 11: an account still on the default seeded password must change it
    if login.password == "admin123":
        from .login import ChangePasswordDialog

        change = ChangePasswordDialog(users, login.user_id, login.password)
        if change.exec() != QDialog.Accepted:
            return 0

    camera_factory, simulation = _make_camera_factory()
    camera_ids, camera_recipe_ids = _select_station(sf)

    window = MainWindow(
        username=login.username,
        recipe=build_code_demo_recipe(),
        camera_factory=camera_factory,
        camera_ids=camera_ids,
        camera_recipe_ids=camera_recipe_ids,
        session_factory=sf,
        user_id=login.user_id,
        simulation=simulation,
    )
    window.resize(1100, 580)
    window.show()
    return app.exec()


def _select_station(session_factory):
    """If stations are configured, let the operator pick one and return its
    (camera_ids, {camera_id: recipe_id}); otherwise a single default camera."""
    from PySide6.QtWidgets import QInputDialog

    from ..db.stations import StationRepository

    repo = StationRepository(session_factory)
    stations = repo.list_stations()
    if not stations:
        return None, None
    if len(stations) == 1:
        sid = stations[0][0]  # one station → just use it, no prompt
    else:
        labels = [f"{name}{(' / ' + line) if line else ''}" for _sid, name, line in stations]
        choice, ok = QInputDialog.getItem(None, "Select station", "Station:", labels, 0, False)
        if not ok:
            return None, None
        sid = stations[labels.index(choice)][0]
    cams = repo.camera_recipes(sid)
    if not cams:
        return None, None
    camera_ids = [name for _cid, name, _rid in cams]
    camera_recipe_ids = {name: rid for _cid, name, rid in cams if rid is not None}
    return camera_ids, camera_recipe_ids


if __name__ == "__main__":
    raise SystemExit(main())
