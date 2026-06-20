"""Read GigE stream-channel settings that commonly cause fetch() timeouts."""
import os, sys
CTI = os.environ["VIS_GENTL_CTI"]
bindir = os.path.dirname(CTI)
os.add_dll_directory(bindir)
os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
from harvesters.core import Harvester
h = Harvester(); h.add_file(CTI); h.update()
ia = h.create(0); nm = ia.remote_device.node_map
for feat in ("GevSCPSPacketSize", "GevSCPD", "GevSCPHostPort", "GevSCDA",
             "DeviceLinkSpeed", "AcquisitionMode", "AcquisitionFrameRate",
             "Width", "Height", "PayloadSize", "TriggerMode", "TriggerSource"):
    try:
        print(f"  {feat} = {getattr(nm, feat).value}")
    except Exception as e:
        print(f"  {feat} = <n/a: {type(e).__name__}>")
ia.destroy(); h.reset()
