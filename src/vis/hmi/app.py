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

    engine = make_engine()
    init_db(engine)
    users = UserService(make_session_factory(engine))
    _ensure_default_admin(users)

    login = LoginDialog(users)
    if login.exec() != QDialog.Accepted:
        return 0

    window = MainWindow(
        username=login.username,
        recipe=build_code_demo_recipe(),
        camera_factory=_sim_factory,
        session_factory=make_session_factory(engine),
        user_id=login.user_id,
    )
    window.resize(1000, 560)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
