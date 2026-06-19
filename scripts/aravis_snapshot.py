#!/usr/bin/env python3
"""Grab one frame from the GigE camera and save it — a reliable focus/exposure
check tool for macOS (no GTK/arv-viewer needed). Run under an Aravis-capable
interpreter (brew python3):

    /opt/homebrew/bin/python3 scripts/aravis_snapshot.py [--exposure US] [--gain DB] [--out PATH]

Prints the brightness so you can tell whether the lens cap is off / there's
enough light (aim for mean well above ~40), and opens the PNG in Preview.
"""

from __future__ import annotations

import argparse
import struct
import zlib


def _write_png_gray(path: str, arr) -> None:
    """Minimal grayscale PNG writer (no PIL/cv2 needed under brew python)."""
    h, w = arr.shape
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0
        raw.extend(arr[y].tobytes())

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)  # 8-bit grayscale
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exposure", type=float, default=10000.0)  # µs
    p.add_argument("--gain", type=float, default=1.0)          # dB
    p.add_argument("--out", default="/tmp/cam_snapshot.png")
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args()

    import gi
    gi.require_version("Aravis", "0.8")
    from gi.repository import Aravis
    import numpy as np

    import time
    n = 0
    for _ in range(6):
        try:
            Aravis.update_device_list()
            n = Aravis.get_n_devices()
        except Exception:
            n = 0
        if n:
            break
        time.sleep(0.4)
    if n == 0:
        print("No camera found (check cable / IP subnet)")
        return 1
    cam = Aravis.Camera.new(None)
    print("camera:", cam.get_model_name())
    cam.set_pixel_format_from_string("Mono8")
    cam.set_exposure_time(args.exposure)
    cam.set_gain(args.gain)
    buf = cam.acquisition(3_000_000)
    if buf is None:
        print("grab timed out")
        return 2
    w, h = buf.get_image_width(), buf.get_image_height()
    img = np.frombuffer(bytes(buf.get_data()), np.uint8)[: w * h].reshape(h, w)
    mean = float(img.mean())
    verdict = ("TOO DARK — remove lens cap / open aperture / add light"
               if mean < 25 else "bright spots may be clipping — lower exposure/gain"
               if mean > 230 else "looks usable")
    print(f"{w}x{h}  brightness mean={mean:.1f} min={img.min()} max={img.max()}  -> {verdict}")
    _write_png_gray(args.out, img)
    print("saved", args.out)
    if not args.no_open:
        import subprocess
        subprocess.run(["open", args.out], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
