#!/usr/bin/env python3
"""Watch the camera's I/O lines — is the part sensor actually reaching it?

    python scripts/line_monitor.py                 # 30 s, auto-detect producer
    python scripts/line_monitor.py --seconds 60 --cti "C:\\...\\bgapi2_gige.cti"

Run this, then pass a product (or your hand) in front of the sensor.

A camera in hardware-trigger mode with a sensor that never reaches it looks
exactly like a broken application: Start works, the camera opens, and no image
ever appears. This separates the two. If the line TOGGLES, the wiring is good
and the problem is elsewhere. If it never changes, the camera is not seeing the
sensor at all — check the wiring, the polarity/inverter, and the sensor's own
power, not the software.

Close vis-hmi first: a GigE camera can be owned by only one process.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

DEFAULT_CTIS = [
    r"C:\Program Files\Baumer GAPI SDK\Components\Bin\x64\bgapi2_gige.cti",
    r"C:\Program Files\Baumer Camera Explorer\bgapi2_gige.cti",
]


def find_cti(explicit: str | None) -> str:
    for path in [explicit, os.environ.get("VIS_GENTL_CTI"), *DEFAULT_CTIS]:
        if path and os.path.isfile(path):
            return path
    sys.exit("no GenTL producer (.cti) found — pass --cti or set VIS_GENTL_CTI")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--cti", default=None)
    ap.add_argument("--serial", default=None, help="exact camera (else the first found)")
    args = ap.parse_args()

    try:
        from harvesters.core import Harvester
    except ImportError:
        sys.exit('harvesters is not installed:  pip install -e ".[camera]"')

    cti = find_cti(args.cti)
    h = Harvester()
    h.add_file(cti)
    h.update()
    if not h.device_info_list:
        sys.exit("no GigE camera found — is it powered, linked and on this subnet?")

    index = 0
    if args.serial:
        matches = [i for i, d in enumerate(h.device_info_list)
                   if str(getattr(d, "serial_number", "")).strip() == args.serial]
        if not matches:
            sys.exit(f"no camera with serial {args.serial!r}")
        index = matches[0]

    try:
        ia = h.create(index)
    except Exception as exc:
        sys.exit(f"cannot open the camera (is vis-hmi still running?): {exc}")

    nm = ia.remote_device.node_map
    try:
        names = [n for n in nm.LineSelector.symbolics]
    except Exception:
        names = ["Line0", "Line1", "Line2"]

    # only the inputs can carry a sensor; the output is ours to drive
    inputs = []
    for name in names:
        try:
            nm.LineSelector.value = name
            if nm.LineMode.value == "Input":
                inputs.append(name)
        except Exception:
            pass

    print(f"camera : {getattr(h.device_info_list[index], 'model', '?')} "
          f"#{getattr(h.device_info_list[index], 'serial_number', '?')}")
    print(f"inputs : {', '.join(inputs) or 'none reported'}")
    try:
        print(f"trigger: TriggerMode={nm.TriggerMode.value} "
              f"TriggerSource={nm.TriggerSource.value}")
    except Exception:
        pass
    print(f"\nwatching for {args.seconds:.0f}s — pass a product in front of the sensor\n")

    seen: dict[str, set] = {n: set() for n in inputs}
    last = None
    end = time.time() + args.seconds
    try:
        while time.time() < end:
            state = {}
            for name in inputs:
                try:
                    nm.LineSelector.value = name
                    state[name] = bool(nm.LineStatus.value)
                    seen[name].add(state[name])
                except Exception:
                    pass
            if state != last:
                print(f"  {time.strftime('%H:%M:%S')}  " +
                      "  ".join(f"{n}={'HIGH' if v else 'low '}" for n, v in state.items()))
                last = state
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass

    print("\nresult:")
    toggled = False
    for name in inputs:
        changed = len(seen[name]) > 1
        toggled = toggled or changed
        print(f"  {name}: {'TOGGLED — the sensor reaches the camera' if changed else 'never changed'}"
              f"   (seen: {sorted(seen[name])})")
    if not toggled:
        print("\n  No input changed. The camera is not seeing the sensor — check the\n"
              "  wiring to the input line, the polarity (LineInverter), and that the\n"
              "  sensor is powered. Until this toggles, a hardware trigger cannot fire.")
    else:
        print("\n  Wiring is good. Set Settings → Camera → Trigger to 'hardware' with\n"
              "  Source set to the line that toggled.")

    ia.destroy()
    h.reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
