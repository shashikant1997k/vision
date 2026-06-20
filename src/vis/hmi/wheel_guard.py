"""Stop the mouse wheel from silently changing combo-box / spin-box values.

By default Qt lets a wheel scroll over an unfocused QComboBox/QSpinBox change
its value — so scrolling a page accidentally edits fields. This app-wide filter
blocks that: an unfocused combo/spin ignores the wheel, and the scroll is
forwarded to the enclosing scroll area so the page scrolls as expected. Values
change only by clicking and choosing.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
)


class WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel and isinstance(
            obj, (QComboBox, QAbstractSpinBox)
        ) and not obj.hasFocus():
            area = obj
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:  # scroll the page instead of changing the value
                QApplication.sendEvent(area.viewport(), event)
            return True  # never let the wheel edit an unfocused field
        return super().eventFilter(obj, event)
