"""Background frame grabber for live previews.

A camera grab BLOCKS until a frame arrives or the timeout expires. Calling it
from a Qt timer therefore blocks the GUI thread for the whole timeout, and on a
triggered camera with an idle line that is the entire time — the window stops
repainting and clicks are never processed, which reads as "the application is
broken" when the camera is working perfectly.

So: one background thread owns the grabbing and keeps only the newest frame; the
GUI reads that slot and never waits. Old frames are dropped rather than queued —
a preview wants what the camera sees NOW, not a backlog to catch up on.
"""

from __future__ import annotations

from threading import Event, Lock, Thread


class PreviewGrabber:
    """Continuously grab from `source`, exposing only the most recent frame."""

    def __init__(self, source, timeout: float = 0.3) -> None:
        self._source = source
        self._timeout = timeout
        self._lock = Lock()
        self._image = None
        self._frames = 0
        self._stop = Event()
        self._thread = Thread(target=self._run, name="preview-grab", daemon=True)
        self._thread.start()

    def _grab_once(self):
        grab = getattr(self._source, "grab", None)
        if callable(grab):
            try:
                return grab(timeout=self._timeout)
            except TypeError:
                return grab()  # camera whose grab() takes no timeout
        return next(self._source.frames(), None)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._grab_once()
            except Exception:
                # A camera unplugged mid-preview must not kill the thread with a
                # traceback the GUI never sees; keep the last good frame.
                if self._stop.wait(0.2):
                    break
                continue
            if frame is not None:
                with self._lock:
                    self._image = frame.image
                    self._frames += 1

    def latest(self):
        """The newest frame's image, or None if nothing has arrived yet."""
        with self._lock:
            return self._image

    def frame_count(self) -> int:
        with self._lock:
            return self._frames

    def stop(self) -> None:
        """Stop grabbing and wait for the thread, so the camera can be closed
        safely — closing it underneath a live grab is a crash in the driver."""
        self._stop.set()
        self._thread.join(timeout=max(2.0, self._timeout * 3))
