"""Lighting / strobe control.

Industrial inspection lighting is driven continuously or strobed (synchronised
to the camera trigger). Real controllers vary (dedicated strobe controllers,
Modbus, or a simple digital output); this keeps the runtime decoupled from them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..io.digital_io import DigitalIO


class LightMode(str, Enum):
    OFF = "off"
    CONTINUOUS = "continuous"
    STROBED = "strobed"  # pulsed in sync with the camera trigger


@dataclass
class LightSettings:
    mode: LightMode = LightMode.CONTINUOUS
    brightness: int = 100  # 0..100 percent
    strobe_source: str = ""  # trigger source when strobed

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "brightness": self.brightness,
            "strobe_source": self.strobe_source,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> LightSettings:
        d = d or {}
        return cls(
            mode=LightMode(d.get("mode", "continuous")),
            brightness=int(d.get("brightness", 100)),
            strobe_source=d.get("strobe_source", ""),
        )


class LightController(ABC):
    @abstractmethod
    def apply(self, channel: int, settings: LightSettings) -> None: ...

    def off(self, channel: int) -> None:
        self.apply(channel, LightSettings(mode=LightMode.OFF, brightness=0))

    def close(self) -> None:  # noqa: B027 - optional override
        pass


class SimulatedLightController(LightController):
    """Records the last-applied settings per channel — for dev and tests."""

    def __init__(self) -> None:
        self.state: dict[int, LightSettings] = {}

    def apply(self, channel: int, settings: LightSettings) -> None:
        self.state[channel] = settings


class DigitalIOLight(LightController):
    """Simple on/off lighting via a DigitalIO channel (no dimming): the light is
    on when mode != OFF and brightness > 0."""

    def __init__(self, io: DigitalIO) -> None:
        self.io = io

    def apply(self, channel: int, settings: LightSettings) -> None:
        on = settings.mode is not LightMode.OFF and settings.brightness > 0
        self.io.write(channel, on)

    def close(self) -> None:
        self.io.close()
