import pytest

from vis.camera import (
    CameraInfo,
    DigitalIOLight,
    LightMode,
    LightSettings,
    SimulatedLightController,
    StaticDiscovery,
)
from vis.camera.discovery import HarvesterDiscovery
from vis.io import SimulatedIO


def test_static_discovery_lists_cameras():
    cams = [CameraInfo(id="cam1", model="MV-CA050"), CameraInfo(id="cam2")]
    found = StaticDiscovery(cams).discover()
    assert [c.id for c in found] == ["cam1", "cam2"]


def test_harvester_discovery_clear_error_without_driver():
    with pytest.raises(RuntimeError):
        HarvesterDiscovery(cti_path=None).discover()  # no harvesters / no producer


def test_light_settings_roundtrip():
    s = LightSettings(mode=LightMode.STROBED, brightness=70, strobe_source="Line1")
    assert LightSettings.from_dict(s.to_dict()) == s


def test_simulated_light_controller():
    lc = SimulatedLightController()
    lc.apply(1, LightSettings(brightness=80))
    assert lc.state[1].brightness == 80
    lc.off(1)
    assert lc.state[1].mode is LightMode.OFF


def test_digital_io_light_on_off():
    io = SimulatedIO()
    lc = DigitalIOLight(io)
    lc.apply(3, LightSettings(mode=LightMode.CONTINUOUS, brightness=100))
    assert (3, True) in io.events
    lc.off(3)
    assert (3, False) in io.events
