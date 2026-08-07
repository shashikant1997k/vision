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

    def __init__(self, session_factory, client_factory=None, target_provider=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PLC parameters")
        self._settings = SettingsService(session_factory)
        self._client_factory = client_factory or (lambda: SimulatedRegisterClient())
        # `target_provider()` returns "host:port" for a real PLC, or None when
        # nothing is configured and reads/writes go to the in-memory simulator.
        self._target_provider = target_provider or (lambda: None)

        # Say WHICH PLC — or that there isn't one. Without this the screen reads
        # a simulator that answers 0 to everything and reports "Read 3
        # parameter(s)", and an engineer takes those zeros for the real machine.
        self._target = QLabel("")
        self._target.setWordWrap(True)

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
        test = QPushButton("Test connection")
        test.setToolTip("Open a connection to the PLC and close it — checks the "
                        "address, port and network without changing anything.")
        test.clicked.connect(self._test)

        buttons = QHBoxLayout()
        for b in (add, remove, read, upload_btn, save, test):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self._status = QLabel("")
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        root.addWidget(self._target)
        root.addWidget(self._table, 1)
        root.addLayout(buttons)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.resize(640, 420)
        self._refresh_target()

    def _refresh_target(self) -> str | None:
        """Update the banner naming the PLC. Returns the target, or None when
        no PLC is configured (so reads/writes hit the simulator)."""
        target = None
        try:
            target = self._target_provider()
        except Exception:
            target = None
        if target:
            self._target.setText(f"PLC: {target}  (Modbus TCP)")
            self._target.setStyleSheet("color:#1a8; font-weight:bold; padding:4px")
        else:
            self._target.setText(
                "⚠  NO PLC CONFIGURED — values below are a built-in simulator, not "
                "your machine. Set the PLC address in Settings → Comms "
                "(I/O backend = modbus, host, port)."
            )
            self._target.setStyleSheet(
                "color:#b33; font-weight:bold; padding:4px; "
                "background:#fee; border:1px solid #b33"
            )
        return target

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
        target = self._refresh_target()
        try:
            client = self._client_factory()
        except Exception as exc:
            self._status.setText(f"Cannot connect to PLC: {exc}")
            return
        errors: list[tuple[str, str]] = []
        try:
            values = read_all(client, params, errors)
        finally:
            client.close()
        for r in range(self._table.rowCount()):      # clear stale values first
            if self._table.item(r, 3):
                self._table.item(r, 3).setText("")
        for name, value in values.items():
            r = self._row_for(name)
            if r >= 0:
                self._table.item(r, 3).setText(str(value))
        where = target or "the SIMULATOR (no PLC configured)"
        if errors:
            failed = ", ".join(f"{n} ({why})" for n, why in errors[:3])
            self._status.setText(
                f"Read {len(values)} of {len(params)} from {where}. "
                f"Could not read: {failed}"
            )
        else:
            self._status.setText(f"Read {len(values)} parameter(s) from {where}.")

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
        target = self._refresh_target()
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
        # Name the target on a WRITE especially: this changes machine behaviour,
        # and "which PLC did that go to?" must never be a guess.
        where = target or "the SIMULATOR (no PLC configured — nothing was sent to a machine)"
        unwritten = [n for n in new_values if n not in written]
        note = f"  Not written: {', '.join(unwritten)}." if unwritten else ""
        self._status.setText(
            f"Uploaded {len(written)} value(s) to {where} and re-read.{note}"
        )

    def _test(self) -> None:
        """Connect and disconnect — proves the address/port/network before an
        engineer starts wondering why a register reads zero."""
        target = self._refresh_target()
        if target is None:
            self._status.setText(
                "No PLC configured — nothing to test. Set I/O backend = modbus "
                "with the host and port in Settings → Comms."
            )
            return
        try:
            client = self._client_factory()
        except Exception as exc:
            self._status.setText(f"FAILED to reach {target}: {exc}")
            return
        try:
            client.close()
        except Exception:
            pass
        self._status.setText(f"Connected to {target} successfully.")

    def _save(self) -> None:
        self._settings.set(PLC_PARAMS_KEY, [p.to_dict() for p in self._params()])
        self._status.setText("Parameter list saved.")
