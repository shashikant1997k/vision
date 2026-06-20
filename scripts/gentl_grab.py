"""Open the discovered GigE camera and grab a single frame, end-to-end through
harvesters. Confirms control + stream channels, not just discovery.

Hardened: forces a 1500-byte stream packet size (no jumbo frames needed) and
tears down cleanly even on timeout, so a blocked stream can't wedge the camera.

Usage:
  VIS_GENTL_CTI=<...bgapi2_gige.cti>  python scripts/gentl_grab.py
"""
import os
import sys

CTI = os.environ.get("VIS_GENTL_CTI")
if not CTI or not os.path.exists(CTI):
    sys.exit(f"VIS_GENTL_CTI not set or missing: {CTI!r}")
bindir = os.path.dirname(CTI)
os.add_dll_directory(bindir)
os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

from harvesters.core import Harvester


def _try_set(nm, name, value):
    try:
        getattr(nm, name).value = value
        return True
    except Exception:
        return False


h = Harvester()
h.add_file(CTI)
h.update()
print(f"devices: {len(h.device_info_list)}")
if not h.device_info_list:
    sys.exit("no camera discovered (power-cycle it / check link)")

ia = h.create(0)
try:
    nm = ia.remote_device.node_map
    for feat in ("GevCurrentIPAddress", "DeviceModelName", "PixelFormat"):
        try:
            v = getattr(nm, feat).value
            if feat == "GevCurrentIPAddress":
                v = ".".join(str((int(v) >> s) & 0xFF) for s in (24, 16, 8, 0))
            print(f"  {feat} = {v}")
        except Exception as e:
            print(f"  {feat} = <n/a: {e}>")
    # safe stream packet size (NIC MTU is 1500; avoid jumbo-frame drops)
    print("  set GevSCPSPacketSize=1500:", _try_set(nm, "GevSCPSPacketSize", 1500))
    _try_set(nm, "AcquisitionMode", "Continuous")
    # free-run: a camera left in hardware/software trigger mode produces NO
    # frames on start() until a trigger fires -> fetch() times out. Force it off.
    for sel in ("FrameStart", "AcquisitionStart"):
        _try_set(nm, "TriggerSelector", sel)
        _try_set(nm, "TriggerMode", "Off")
    for feat in ("TriggerMode", "TriggerSource", "ExposureTime", "AcquisitionFrameRate"):
        try:
            print(f"  {feat} = {getattr(nm, feat).value}")
        except Exception:
            pass

    ia.start()
    print("acquisition started; fetching one frame (5s timeout)...")
    try:
        with ia.fetch(timeout=5) as buf:
            c = buf.payload.components[0]
            print(f"FRAME OK: {c.width}x{c.height}, {len(c.data)} bytes, "
                  f"min={c.data.min()} max={c.data.max()}")
    finally:
        try:
            ia.stop()
        except Exception as e:
            print(f"  (stop noted: {type(e).__name__})")
finally:
    try:
        ia.destroy()
    except Exception:
        pass
    try:
        h.reset()
    except Exception:
        pass
print("done.")
