from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..engine.aggregator import RegionResult


class Transport(Protocol):
    def publish(self, message: str) -> None: ...
    def close(self) -> None: ...


class ResultPublisher:
    """Bridges inspection results to an external transport using a formatter.

    Wire it up with:  bus.subscribe("inspection.result", publisher.on_result)
    """

    def __init__(self, transport: Transport, formatter: Callable[[RegionResult], str]) -> None:
        self.transport = transport
        self.formatter = formatter

    def on_result(self, result: RegionResult) -> None:
        self.transport.publish(self.formatter(result))
