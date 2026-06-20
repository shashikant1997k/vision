from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.app_settings import SettingsService
from ..integrations.plc_params import (
    PlcParameter,
    SimulatedRegisterClient,
    read_all,
    upload,
)

PLC_PARAMS_KEY = "plc_params"
_KINDS = ("holding", "coil")


def load_plc_params(session_factory) -> list[PlcParameter]:
    saved = SettingsService(session_factory).get(PLC_PARAMS_KEY) or []
    return [PlcParameter.from_dict(d) for d in saved]


class PlcParametersWindow(QMainWindow):
    """Read/edit/upload named PLC registers (CodeScan-style PLC Parameters).

    `client_factory()` returns a fresh RegisterClient (a real ModbusRegisterClient
    in production, or the in-memory simulator). It is opened on demand for Read /
    Upload and closed afterwards, so the window never holds the PLC socket open.
    """

    COLS = ["Name", "Address", "Type", "Current", "New value"]

    def __init__(self, session_factory, client_factory=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PLC parameters")
        self._settings = SettingsService(session_factory)
        self._client_factory = client_factory or (lambda: SimulatedRegisterClient())

        self._table = QTableWidget(0, len(self.COLS))
        self._table.setHorizontalHeaderLabels(self.COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        for p in load_plc_params(session_factory):
            self._add_row(p)
        if self._table.rowCount() == 0:
            self._add_row(PlcParameter("", 0, "holding"))

        add = QPushButton("Add row")
        add.clicked.connect(lambda: self._add_row(PlcParameter("", 0, "holding")))
        remove = QPushButton("Remove row")
        remove.clicked.connect(self._remove_row)
        read = QPushButton("Read")
        read.setToolTip("Read the current value of every parameter from the PLC.")
        read.clicked.connect(self._read)
        upload_btn = QPushButton("Upload")
        upload_btn.setProperty("variant", "primary")
        upload_btn.setToolTip("Write the entered New values to the PLC, then re-read.")
        upload_btn.clicked.connect(self._upload)
        save = QPushButton("Save list")
        save.setToolTip("Persist the parameter definitions (names/addresses).")
        save.clicked.connect(self._save)

        buttons = QHBoxLayout()
        for b in (add, remove, read, upload_btn, save):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self._status = QLabel("")
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        root.addWidget(self._table, 1)
        root.addLayout(buttons)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(640, 420)

    # --- table helpers ----------------------------------------------------
    def _add_row(self, p: PlcParameter) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, QTableWidgetItem(p.name))
        self._table.setItem(r, 1, QTableWidgetItem(str(p.address)))
        kind = QComboBox()
        kind.addItems(_KINDS)
        kind.setCurrentText(p.kind if p.kind in _KINDS else "holding")
        self._table.setCellWidget(r, 2, kind)
        current = QTableWidgetItem("")
        current.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)  # read-only
        self._table.setItem(r, 3, current)
        self._table.setItem(r, 4, QTableWidgetItem(""))

    def _remove_row(self) -> None:
        r = self._table.currentRow()
        if r >= 0:
            self._table.removeRow(r)

    def _params(self) -> list[PlcParameter]:
        params = []
        for r in range(self._table.rowCount()):
            name = (self._table.item(r, 0).text() if self._table.item(r, 0) else "").strip()
            if not name:
                continue
            try:
                address = int((self._table.item(r, 1).text() if self._table.item(r, 1) else "0") or 0)
            except ValueError:
                address = 0
            kind = self._table.cellWidget(r, 2).currentText()
            params.append(PlcParameter(name, address, kind))
        return params

    def _row_for(self, name: str) -> int:
        for r in range(self._table.rowCount()):
            if self._table.item(r, 0) and self._table.item(r, 0).text().strip() == name:
                return r
        return -1

    # --- actions ----------------------------------------------------------
    def _read(self) -> None:
        params = self._params()
        if not params:
            self._status.setText("Add at least one named parameter first.")
            return
        try:
            client = self._client_factory()
        except Exception as exc:
            self._status.setText(f"Cannot connect to PLC: {exc}")
            return
        try:
            values = read_all(client, params)
        finally:
            client.close()
        for name, value in values.items():
            r = self._row_for(name)
            if r >= 0:
                self._table.item(r, 3).setText(str(value))
        self._status.setText(f"Read {len(values)} parameter(s).")

    def _upload(self) -> None:
        params = self._params()
        new_values: dict[str, int] = {}
        for p in params:
            r = self._row_for(p.name)
            text = (self._table.item(r, 4).text() if r >= 0 and self._table.item(r, 4) else "").strip()
            if text:
                try:
                    new_values[p.name] = int(text)
                except ValueError:
                    self._status.setText(f"'{text}' is not a whole number ({p.name}).")
                    return
        if not new_values:
            self._status.setText("Enter a New value on at least one row.")
            return
        try:
            client = self._client_factory()
        except Exception as exc:
            self._status.setText(f"Cannot connect to PLC: {exc}")
            return
        try:
            written = upload(client, params, new_values)
            values = read_all(client, params)
        finally:
            client.close()
        for name, value in values.items():
            r = self._row_for(name)
            if r >= 0:
                self._table.item(r, 3).setText(str(value))
                self._table.item(r, 4).setText("")
        self._status.setText(f"Uploaded {len(written)} value(s) and re-read.")

    def _save(self) -> None:
        self._settings.set(PLC_PARAMS_KEY, [p.to_dict() for p in self._params()])
        self._status.setText("Parameter list saved.")
