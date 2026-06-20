from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class TriggerMode(str, Enum):
    CONTINUOUS = "continuous"  # free-run
    SOFTWARE = "software"
    HARDWARE = "hardware"  # external line trigger
    ENCODER = "encoder"  # shaft-encoder trigger (line tracking, D-011)


@dataclass
class TriggerConfig:
    mode: TriggerMode = TriggerMode.CONTINUOUS
    source: str = ""  # e.g. "Line1", "EncoderA/B"
    delay_us: int = 0
    divider: int = 1  # encoder pulses per trigger
    debounce_us: int = 0  # ignore trigger edges within this window (anti-bounce)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "source": self.source,
            "delay_us": self.delay_us,
            "divider": self.divider,
            "debounce_us": self.debounce_us,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> TriggerConfig:
        d = d or {}
        return cls(
            mode=TriggerMode(d.get("mode", "continuous")),
            source=d.get("source", ""),
            delay_us=int(d.get("delay_us", 0)),
            divider=int(d.get("divider", 1)),
            debounce_us=int(d.get("debounce_us", 0)),
        )


@dataclass
class SensorROI:
    """Acquisition window on the sensor (distinct from an inspection ROI).
    w/h == 0 means full sensor."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


@dataclass
class LightingConfig:
    """Illumination control (bar/dome/coaxial light via a controller or the
    camera's strobe output). Strobe freezes motion synced to the trigger."""

    brightness: int = 100  # 0–100 %
    strobe: bool = False  # pulse the light synced to the trigger/exposure
    strobe_delay_us: int = 0  # delay from trigger to light-on
    strobe_width_us: int = 2000  # light-on duration
    channel: str = ""  # controller channel/id

    def to_dict(self) -> dict:
        return {
            "brightness": self.brightness,
            "strobe": self.strobe,
            "strobe_delay_us": self.strobe_delay_us,
            "strobe_width_us": self.strobe_width_us,
            "channel": self.channel,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> LightingConfig:
        d = d or {}
        return cls(
            brightness=int(d.get("brightness", 100)),
            strobe=bool(d.get("strobe", False)),
            strobe_delay_us=int(d.get("strobe_delay_us", 0)),
            strobe_width_us=int(d.get("strobe_width_us", 2000)),
            channel=d.get("channel", ""),
        )


@dataclass
class CameraSettings:
    exposure_us: int = 5000
    gain_db: float = 0.0
    frame_rate: float = 30.0
    white_balance: str = "auto"
    packet_size: int = 9000  # jumbo frames for GigE (D-011)
    gamma: float = 1.0
    black_level: int = 0  # sensor black-level offset (0 = leave default)
    sharpness: int = 0    # sharpening strength (0 = off)
    sensor_roi: SensorROI = field(default_factory=SensorROI)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)

    def to_dict(self) -> dict:
        return {
            "exposure_us": self.exposure_us,
            "gain_db": self.gain_db,
            "frame_rate": self.frame_rate,
            "white_balance": self.white_balance,
            "packet_size": self.packet_size,
            "gamma": self.gamma,
            "black_level": self.black_level,
            "sharpness": self.sharpness,
            "sensor_roi": asdict(self.sensor_roi),
            "trigger": self.trigger.to_dict(),
            "lighting": self.lighting.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> CameraSettings:
        d = d or {}
        roi = d.get("sensor_roi") or {}
        return cls(
            exposure_us=int(d.get("exposure_us", 5000)),
            gain_db=float(d.get("gain_db", 0.0)),
            frame_rate=float(d.get("frame_rate", 30.0)),
            white_balance=d.get("white_balance", "auto"),
            packet_size=int(d.get("packet_size", 9000)),
            gamma=float(d.get("gamma", 1.0)),
            black_level=int(d.get("black_level", 0)),
            sharpness=int(d.get("sharpness", 0)),
            sensor_roi=SensorROI(
                x=int(roi.get("x", 0)),
                y=int(roi.get("y", 0)),
                w=int(roi.get("w", 0)),
                h=int(roi.get("h", 0)),
            ),
            trigger=TriggerConfig.from_dict(d.get("trigger")),
            lighting=LightingConfig.from_dict(d.get("lighting")),
        )
