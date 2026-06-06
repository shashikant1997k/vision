from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    """Minimal in-process pub/sub. This is the internal result/event bus that
    Phase-2 serialization will subscribe to without touching the engine (D-003).
    """

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: Any) -> None:
        for handler in list(self._subs.get(topic, ())):
            handler(payload)
