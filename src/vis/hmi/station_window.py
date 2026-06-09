from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..db.stations import StationRepository
from ..db.store import RecipeRepository


class StationConfigWindow(QMainWindow):
    """Admin: define stations and the cameras on them, and assign the recipe each
    camera runs. Persisted (RBAC-gated + audited); the live screen can load a
    station's camera→recipe map instead of hand-picking per run."""

    def __init__(self, session_factory, user_id, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stations & cameras")
        self._repo = StationRepository(session_factory)
        self._recipes = RecipeRepository(session_factory)
        self._user_id = user_id
        self._station_id = None

        self._station_combo = QComboBox()
        self._station_combo.currentIndexChanged.connect(self._load_cameras)
        new_station = QPushButton("New station…")
        new_station.clicked.connect(self._new_station)
        top = QHBoxLayout()
        top.addWidget(QLabel("Station"))
        top.addWidget(self._station_combo, 1)
        top.addWidget(new_station)

        self._cam_form = QFormLayout()
        cam_box = QWidget()
        cam_box.setLayout(self._cam_form)

        self._cam_name = QLineEdit()
        self._cam_name.setPlaceholderText("camera name, e.g. cam1")
        self._cam_ident = QLineEdit()
        self._cam_ident.setPlaceholderText("IP / serial (optional)")
        add_cam = QPushButton("Add camera")
        add_cam.clicked.connect(self._add_camera)
        add_row = QHBoxLayout()
        add_row.addWidget(self._cam_name, 1)
        add_row.addWidget(self._cam_ident, 1)
        add_row.addWidget(add_cam)

        self._status = QLabel("")
        root = QVBoxLayout()
        root.addLayout(top)
        root.addWidget(QLabel("Cameras (assign the recipe each one runs):"))
        root.addWidget(cam_box, 1)
        root.addLayout(add_row)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        self._reload_stations()

    def _recipe_items(self):
        items = [("— none —", None)]
        for rid, name, version in self._recipes.list_approved():
            items.append((f"{name} v{version}", rid))
        return items

    def _reload_stations(self) -> None:
        self._station_combo.blockSignals(True)
        self._station_combo.clear()
        for sid, name, line in self._repo.list_stations():
            self._station_combo.addItem(f"{name}{(' / ' + line) if line else ''}", sid)
        self._station_combo.blockSignals(False)
        self._load_cameras()

    def _new_station(self) -> None:
        name, ok = QInputDialog.getText(self, "New station", "Station name:")
        if not ok or not name.strip():
            return
        try:
            self._repo.create_station(name.strip(), self._user_id)
        except Exception as exc:
            self._status.setText(f"Create failed: {exc}")
            return
        self._reload_stations()
        self._station_combo.setCurrentIndex(self._station_combo.count() - 1)

    def _add_camera(self) -> None:
        if self._station_id is None:
            self._status.setText("Create or select a station first.")
            return
        name = self._cam_name.text().strip()
        if not name:
            self._status.setText("Enter a camera name.")
            return
        try:
            self._repo.add_camera(self._station_id, name, self._user_id, identifier=self._cam_ident.text().strip())
        except Exception as exc:
            self._status.setText(f"Add camera failed: {exc}")
            return
        self._cam_name.clear()
        self._cam_ident.clear()
        self._load_cameras()

    def _load_cameras(self) -> None:
        while self._cam_form.rowCount():
            self._cam_form.removeRow(0)
        self._station_id = self._station_combo.currentData()
        if self._station_id is None:
            return
        items = self._recipe_items()
        for cam_id, cam_name, recipe_id in self._repo.camera_recipes(self._station_id):
            combo = QComboBox()
            for label, data in items:
                combo.addItem(label, data)
            idx = combo.findData(recipe_id)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentIndexChanged.connect(lambda _i, c=cam_id, cb=combo: self._assign(c, cb))
            self._cam_form.addRow(cam_name, combo)

    def _assign(self, camera_id, combo) -> None:
        try:
            self._repo.set_camera_recipe(camera_id, combo.currentData(), self._user_id)
            self._status.setText("Recipe assignment saved.")
        except Exception as exc:
            self._status.setText(f"Save failed: {exc}")
