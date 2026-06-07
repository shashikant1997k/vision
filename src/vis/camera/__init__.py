"""Camera hardware module — vendor-neutral acquisition + control.

Layers:
  settings.py     CameraSettings, TriggerConfig (exposure/gain/trigger/ROI/...)
  device.py       CameraDevice — controllable camera interface (open/configure/grab)
  file_source.py  FileCamera — replay images from disk (offline test / dev on macOS)
  genicam.py      HarvesterCamera — real GigE Vision / GenICam driver (Windows, D-011)
  manager.py      CameraManager — manage multiple cameras on a station
  calibration.py  Calibration — pixel <-> mm

Real GenICam acquisition runs on the Windows line PC; everything else is
testable on macOS via the file/simulation sources behind the same interface.
"""

from .calibration import Calibration
from .device import CameraDevice, CameraInfo
from .discovery import CameraDiscovery, HarvesterDiscovery, StaticDiscovery
from .focus import FocusAssist, focus_score
from .file_source import FileCamera
from .lighting import DigitalIOLight, LightController, LightMode, LightSettings, SimulatedLightController
from .manager import CameraManager
from .settings import CameraSettings, SensorROI, TriggerConfig, TriggerMode

__all__ = [
    "Calibration",
    "CameraDevice",
    "CameraDiscovery",
    "CameraInfo",
    "CameraManager",
    "CameraSettings",
    "DigitalIOLight",
    "FileCamera",
    "FocusAssist",
    "HarvesterDiscovery",
    "focus_score",
    "LightController",
    "LightMode",
    "LightSettings",
    "SensorROI",
    "SimulatedLightController",
    "StaticDiscovery",
    "TriggerConfig",
    "TriggerMode",
]
