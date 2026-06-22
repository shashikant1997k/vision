from __future__ import annotations

from collections.abc import Iterable

from .workers import ToolOutcome, ToolTask, run_tool_task, worker_init


class SyncPool:
    """Runs tasks in-process. For tests, single-core fallback, and debugging."""

    def map(self, tasks: Iterable[ToolTask]) -> list[ToolOutcome]:
        return [run_tool_task(t) for t in tasks]

    def close(self) -> None:
        pass


class ThreadPool:
    """Runs a frame's tools on a thread pool, sharing the one in-process OCR
    model. ONNX Runtime and OpenCV release the GIL during inference/transform, so
    OCR-bound tools run truly in parallel — without the per-worker model load,
    process spawn, and IPC pickling of ProcessPool. Right choice for line speed
    (e.g. a QR + 5 text lines must finish well inside the cycle-time budget)."""

    def __init__(self, workers: int) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._ex = ThreadPoolExecutor(max_workers=max(1, workers))

    def map(self, tasks: Iterable[ToolTask]) -> list[ToolOutcome]:
        return list(self._ex.map(run_tool_task, list(tasks)))

    def close(self) -> None:
        self._ex.shutdown(wait=False)


class ProcessPool:
    """Multiprocessing worker pool with warm processes (see docs/05).

    Scale workers by process count (~cores - 2); keep per-worker inference
    single-threaded to avoid oversubscription.
    """

    def __init__(self, workers: int) -> None:
        from concurrent.futures import ProcessPoolExecutor

        self._ex = ProcessPoolExecutor(max_workers=workers, initializer=worker_init)

    def map(self, tasks: Iterable[ToolTask]) -> list[ToolOutcome]:
        return list(self._ex.map(run_tool_task, list(tasks)))

    def close(self) -> None:
        self._ex.shutdown()
