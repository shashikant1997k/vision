"""OCV font manager: the Cognex/Keyence-style font-training workflow.

List the trained fonts; create a new font; TRAIN any font from a sample image of
real print — the sample is segmented into characters, each glyph is shown with
its suggested character for the operator to confirm/correct (annotation), and
the labelled glyphs are added to the font model. More samples = better reading.
"""

from __future__ import annotations

import base64

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db.fonts import FontRepository
from ..tools.fontgen import PRINT_TYPES, segment_sample


def _pixmap_from_b64(data: str) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(base64.b64decode(data), "PNG")
    return pm


class TrainFontDialog(QDialog):
    """Segment a sample image → annotate each character → labelled glyphs."""

    def __init__(self, image, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Train font — annotate the characters")
        self._image = image
        self.labelled: list[tuple[str, str]] = []

        self._text = QLineEdit()
        self._text.setPlaceholderText("Type EXACTLY what the sample prints, e.g. LOT420519")
        self._kernel = QSpinBox()
        self._kernel.setRange(0, 25)
        self._kernel.setToolTip("Dot-connect size for dot-matrix print (0 for solid print).")
        segment_btn = QPushButton("Segment")
        segment_btn.setProperty("variant", "primary")
        segment_btn.clicked.connect(self._segment)
        form = QFormLayout()
        form.addRow("Sample says", self._text)
        form.addRow("Dot connect", self._kernel)
        form.addRow(segment_btn)

        self._grid = QGridLayout()
        grid_host = QWidget()
        grid_host.setLayout(self._grid)
        self._edits: list[tuple[QLineEdit, str]] = []

        self._status = QLabel("")
        save_btn = QPushButton("Add to font")
        save_btn.setProperty("variant", "primary")
        save_btn.clicked.connect(self._accept_labels)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Confirm each character (fix any wrong box):"))
        layout.addWidget(grid_host, 1)
        layout.addWidget(self._status)
        layout.addWidget(save_btn)

    def _segment(self) -> None:
        text = self._text.text().strip()
        if not text:
            self._status.setText("Type what the sample says first.")
            return
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._edits = []
        try:
            pairs = segment_sample(self._image, text, dot_kernel=self._kernel.value(), min_area=6)
        except Exception as exc:
            self._status.setText(f"Segmentation failed: {exc}")
            return
        for i, (ch, template) in enumerate(pairs):
            thumb = QLabel()
            thumb.setPixmap(_pixmap_from_b64(template).scaled(36, 48, Qt.KeepAspectRatio))
            thumb.setAlignment(Qt.AlignCenter)
            edit = QLineEdit(ch)
            edit.setMaxLength(1)
            edit.setFixedWidth(36)
            edit.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(thumb, 0, i)
            self._grid.addWidget(edit, 1, i)
            self._edits.append((edit, template))
        self._status.setText(f"{len(pairs)} characters segmented — confirm and Add to font.")

    def _accept_labels(self) -> None:
        if not self._edits:
            self._status.setText("Segment the sample first.")
            return
        self.labelled = [
            (edit.text().strip().upper(), template)
            for edit, template in self._edits
            if edit.text().strip()
        ]
        self.accept()


class FontManagerWindow(QMainWindow):
    """Manage the trained-font library (engineer-level)."""

    def __init__(self, session_factory, user_id, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCV fonts — training")
        self._repo = FontRepository(session_factory)
        self._uid = user_id

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["ID", "Font", "Print type", "Chars", "Samples"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)

        new_btn = QPushButton("New font…")
        new_btn.setProperty("variant", "primary")
        new_btn.clicked.connect(self._new_font)
        train_btn = QPushButton("Train from sample image…")
        train_btn.clicked.connect(self._train)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete)
        bar = QHBoxLayout()
        bar.addWidget(new_btn)
        bar.addWidget(train_btn)
        bar.addWidget(delete_btn)
        bar.addStretch(1)

        self._status = QLabel(
            "Train the customer's actual coder font from a clear line image: "
            "New font… → Train from sample image… → annotate → save."
        )
        self._status.setWordWrap(True)

        root = QVBoxLayout()
        root.addWidget(self._table, 1)
        root.addLayout(bar)
        root.addWidget(self._status)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self._refresh()

    def _refresh(self) -> None:
        fonts = self._repo.list_fonts()
        self._table.setRowCount(len(fonts))
        for r, f in enumerate(fonts):
            for c, value in enumerate((f["id"], f["name"], f["print_type"], f["chars"], f["samples"])):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.UserRole, f["id"])
                self._table.setItem(r, c, item)

    def _selected_font(self):
        row = self._table.currentRow()
        if row < 0:
            return None
        return self._table.item(row, 0).data(Qt.UserRole)

    def _new_font(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("New font")
        name = QLineEdit()
        name.setPlaceholderText("e.g. Line 3 Videojet 7×5")
        ptype = QComboBox()
        for key, label, _kernel in PRINT_TYPES:
            ptype.addItem(label, key)
        ok = QPushButton("Create")
        ok.setProperty("variant", "primary")
        ok.clicked.connect(dialog.accept)
        form = QFormLayout()
        form.addRow("Name", name)
        form.addRow("Print type", ptype)
        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        layout.addWidget(ok)
        if dialog.exec() != QDialog.Accepted or not name.text().strip():
            return
        kernel = next(k for key, _l, k in PRINT_TYPES if key == ptype.currentData())
        try:
            self._repo.create_font(self._uid, name.text().strip(), ptype.currentData(), kernel)
        except Exception as exc:
            self._status.setText(f"Create failed: {exc}")
            return
        self._refresh()

    def _train(self) -> None:
        font_id = self._selected_font()
        if font_id is None:
            self._status.setText("Select a font to train (or create one first).")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Sample image of the print", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if not path:
            return
        from ..camera.file_source import load_image

        try:
            image = load_image(path)
        except Exception as exc:
            self._status.setText(f"Could not load image: {exc}")
            return
        dialog = TrainFontDialog(image, self)
        # suggest the font's dot kernel
        fonts = {f["id"]: f for f in self._repo.list_fonts()}
        dialog._kernel.setValue(fonts.get(font_id, {}).get("dot_kernel", 0))
        dialog.resize(720, 320)
        if dialog.exec() != QDialog.Accepted or not dialog.labelled:
            return
        try:
            total = self._repo.add_samples(self._uid, font_id, dialog.labelled)
        except Exception as exc:
            self._status.setText(f"Training failed: {exc}")
            return
        self._refresh()
        self._status.setText(
            f"Added {len(dialog.labelled)} glyph samples — font now has {total} samples. "
            "Re-teach (or re-select the font) in recipes to use the new training."
        )

    def _delete(self) -> None:
        font_id = self._selected_font()
        if font_id is None:
            return
        try:
            self._repo.delete_font(self._uid, font_id)
        except Exception as exc:
            self._status.setText(f"Delete failed: {exc}")
            return
        self._refresh()
