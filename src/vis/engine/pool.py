from __future__ import annotations

from collections.abc import Iterable

from .workers import ToolOutcome, ToolTask, run_tool_task, worker_init


class SyncPool:
    """Runs tasks in-process. For tests, single-core fallback, and debugging."""

    def map(self, tasks: Iterable[ToolTask]) -> list[ToolOutcome]:
        return [run_tool_task(t) for t in tasks]

    def close(self) -> None:
        pass


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
