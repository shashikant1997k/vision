"""Application theme — a modern, flat design system applied app-wide.

One QSS sheet on top of the Fusion style so every window (login, live, teach,
settings, admin, stations, review) shares the same contemporary look: soft grey
canvas, white cards, rounded inputs with a focus ring, accent-filled primary
buttons, clean tables/tabs, slim scrollbars.

Mark important buttons with  btn.setProperty("variant", "primary"|"danger").
"""

from __future__ import annotations

ACCENT = "#3d6bf5"
ACCENT_HOVER = "#2f5ce4"
DANGER = "#e5484d"
CANVAS = "#eef1f6"
CARD = "#ffffff"
BORDER = "#d9dee8"
TEXT = "#1b1f24"
TEXT_MUTED = "#5b6472"

_QSS = f"""
QMainWindow, QDialog {{ background: {CANVAS}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QLabel {{ background: transparent; }}

/* ---- buttons ---- */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {ACCENT}; background: #f5f8ff; }}
QPushButton:pressed {{ background: #e8eeff; }}
QPushButton:disabled {{ color: #9aa3af; background: #f1f3f6; border-color: #e7eaf0; }}
QPushButton[variant="primary"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:disabled {{
    background: #b9c6f8; border-color: #b9c6f8; color: #f0f3ff;
}}
QPushButton[variant="danger"] {{
    background: {DANGER}; border-color: {DANGER}; color: white; font-weight: 600;
}}
QPushButton[variant="danger"]:hover {{ background: #d63b40; }}
QPushButton[variant="danger"]:disabled {{
    background: #f3b3b5; border-color: #f3b3b5; color: white;
}}

/* ---- inputs ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #cdd9ff;
    selection-color: {TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: #f1f3f6; color: #9aa3af;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    selection-background-color: #e3ebff;
    selection-color: {TEXT};
}}

/* ---- tables / trees ---- */
QTableWidget, QTableView, QTreeWidget, QTreeView, QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: #eef1f5;
    alternate-background-color: #f8fafc;
}}
QHeaderView::section {{
    background: #f1f4f8;
    color: {TEXT_MUTED};
    font-weight: 600;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
}}
QTableWidget::item {{ padding: 4px; }}
QTreeWidget::item {{ padding: 3px; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: #e3ebff; color: {TEXT};
}}
QTableCornerButton::section {{ background: #f1f4f8; border: none; }}

/* ---- tabs ---- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    background: {CARD};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 7px 16px;
    margin-right: 4px;
    border: none;
    color: {TEXT_MUTED};
    font-weight: 500;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    font-weight: 700;
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover {{ color: {TEXT}; }}

/* ---- group boxes (cards) ---- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 8px 8px 8px;
    font-weight: 600;
    color: {TEXT_MUTED};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}}

/* ---- scroll areas / bars ---- */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c6cdd8; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #aab3c2; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c6cdd8; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- misc ---- */
QStatusBar {{ background: #e7ebf2; color: {TEXT_MUTED}; }}
QToolTip {{
    background: {TEXT}; color: white; border: none; padding: 5px 9px;
}}
QCheckBox {{ spacing: 7px; }}
QMessageBox, QInputDialog {{ background: {CANVAS}; }}
"""


def apply_theme(app) -> None:
    """Apply the modern theme to the whole application (call once at startup)."""
    app.setStyle("Fusion")
    app.setStyleSheet(_QSS)
