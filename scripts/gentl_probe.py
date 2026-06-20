"""Probe the Baumer GenTL producer via harvesters: load the .cti and list any
GigE Vision cameras it can see. Confirms the SDK side independent of the HMI.

Usage:
  VIS_GENTL_CTI=<path to bgapi2_gige.cti>  python scripts/gentl_probe.py
"""
import os
import sys

CTI = os.environ.get("VIS_GENTL_CTI")
if not CTI or not os.path.exists(CTI):
    sys.exit(f"VIS_GENTL_CTI not set or missing: {CTI!r}")

# The producer's dependent DLLs sit next to the .cti; make them loadable.
bindir = os.path.dirname(CTI)
os.add_dll_directory(bindir)
os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

from harvesters.core import Harvester

h = Harvester()
h.add_file(CTI)
h.update()
print(f"producer loaded OK: {CTI}")
print(f"devices found: {len(h.device_info_list)}")
for i, d in enumerate(h.device_info_list):
    # device_info attributes vary by producer; print what's available
    fields = {}
    for attr in ("vendor", "model", "serial_number", "id_", "display_name",
                 "tl_type", "user_defined_name"):
        try:
            fields[attr] = getattr(d, attr)
        except Exception:
            pass
    print(f"  [{i}] {fields}")
h.reset()
