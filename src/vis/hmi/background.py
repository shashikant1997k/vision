"""Run blocking work off the GUI thread, keeping every screen responsive.

Any screen that does slow work (OCR over a folder, font training, a camera
grab) should hand it to a BackgroundTask instead of calling it inline — a call
that blocks the GUI thread makes the whole window show "not responding".

Results/errors come back on signals, which Qt delivers on the GUI thread, so
the on_done/on_error callbacks can touch widgets safely.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication


class BackgroundTask(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # surface the error instead of crashing the thread
            self.failed.emit(str(exc))


def run_in_background(owner, fn, on_done, on_error=None, *, attr="_bg_task"):
    """Run fn() off the GUI thread; call on_done(result) / on_error(msg) on the
    GUI thread. The task is stored on `owner.<attr>` so it isn't garbage
    collected mid-run; only one such task per attr runs at a time."""
    existing = getattr(owner, attr, None)
    if existing is not None and existing.isRunning():
        return None  # a task is already running on this slot
    QApplication.setOverrideCursor(Qt.BusyCursor)  # loader: click registered, working
    task = BackgroundTask(fn, owner)

    def _finish_done(result):
        QApplication.restoreOverrideCursor()
        setattr(owner, attr, None)
        on_done(result)

    def _finish_failed(msg):
        QApplication.restoreOverrideCursor()
        setattr(owner, attr, None)
        if on_error is not None:
            on_error(msg)

    task.done.connect(_finish_done)
    task.failed.connect(_finish_failed)
    setattr(owner, attr, task)
    task.start()
    return task
