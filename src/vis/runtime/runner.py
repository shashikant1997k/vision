from __future__ import annotations

from threading import Event, Thread

from ..common.events import EventBus
from ..engine.pipeline import InspectionPipeline
from .live_view import LiveView
from .reject import RejectHandler
from .stats import LiveStats


def _camera_id(camera) -> str:
    return getattr(camera, "camera_id", None) or getattr(
        getattr(camera, "info", None), "id", "cam"
    )


class InspectionRunner:
    """Runs the live loop: one acquisition thread per camera, each feeding the
    shared worker pool through its recipe's pipeline.

    Acquisition is I/O-bound (and the real GenICam grab releases the GIL), so
    threads are the right tool here; the CPU-bound OCR/decode work runs in the
    shared process pool. Each camera's frames are aggregated independently and
    its rejects routed to their lanes.
    """

    def __init__(
        self,
        assignments,  # list[(camera, recipe)]
        pool,
        *,
        bus: EventBus | None = None,
        stats: LiveStats | None = None,
        live_view: LiveView | None = None,
        reject_handler: RejectHandler | None = None,
        failed_log=None,  # optional FailedImageLog for reject review
        on_frame=None,  # optional callback(frame, results) per processed frame
    ) -> None:
        self.assignments = list(assignments)
        self.pool = pool
        self.bus = bus or EventBus()
        self.stats = stats or LiveStats()
        self.live_view = live_view or LiveView()
        self.reject_handler = reject_handler
        self.failed_log = failed_log
        self.on_frame = on_frame
        self._threads: list[Thread] = []
        self._stop = Event()

    def _run_camera(self, camera, pipeline: InspectionPipeline) -> None:
        try:
            for frame in camera.frames():
                if self._stop.is_set():
                    break
                results = pipeline.process_frame(frame)
                self.live_view.update(frame, results)
                any_failed = False
                for r in results:
                    self.stats.record(r)
                    if not r.passed:
                        any_failed = True
                        if self.reject_handler is not None:
                            self.reject_handler.reject(r)
                if any_failed and self.failed_log is not None:
                    self.failed_log.add(frame, results)
                if self.on_frame is not None:
                    self.on_frame(frame, results)
        finally:
            close = getattr(camera, "close", None)
            if callable(close):
                close()

    def start(self) -> InspectionRunner:
        self._stop.clear()
        for camera, recipe in self.assignments:
            pipeline = InspectionPipeline(recipe, self.pool, self.bus)
            thread = Thread(
                target=self._run_camera,
                args=(camera, pipeline),
                name=f"acq-{_camera_id(camera)}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        return self

    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def stop(self) -> None:
        self._stop.set()
        # nudge each camera's frames() loop to exit now, even if it's blocked
        # waiting on a (hardware-triggered) frame that may never arrive
        for camera, _recipe in self.assignments:
            req = getattr(camera, "request_stop", None)
            if callable(req):
                req()

    def join(self) -> None:
        for thread in self._threads:
            thread.join()
        self._threads = []

    def run(self) -> LiveStats:
        """Start and run to completion (for bounded sources). Returns stats."""
        self.start()
        self.join()
        if self.reject_handler is not None:
            self.reject_handler.drain()  # flush pending (delayed) ejects
        return self.stats
