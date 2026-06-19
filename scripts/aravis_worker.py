#!/usr/bin/env python3
"""Aravis acquisition worker — runs under a Python that can import Aravis
(on macOS: Homebrew's python3, which shares glib/girepository with brew's
aravis). It opens the GigE camera, configures it, and streams raw frames to
stdout using a simple length-framed protocol so the main app (a different,
possibly venv Python) can read them without importing the fragile bindings.

Frame on stdout:  MAGIC(4) + w(u32 BE) + h(u32 BE) + pixel(u32 BE) + len(u32 BE) + payload
Status/errors go to stderr. Self-contained: imports only gi + stdlib.

Usage (normally spawned by vis.camera.aravis_proc, not by hand):
    python3 aravis_worker.py --device-index 0 --exposure 5000 --gain 0 \
        --fps 30 --trigger continuous
"""

from __future__ import annotations

import argparse
import struct
import sys

MAGIC = b"VF01"


def _err(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--device-index", type=int, default=0)
    p.add_argument("--device-id", default="")
    p.add_argument("--exposure", type=float, default=5000.0)  # µs
    p.add_argument("--gain", type=float, default=0.0)         # dB
    p.add_argument("--fps", type=float, default=30.0)
    p.add_argument("--trigger", default="continuous")         # continuous|software|hardware
    p.add_argument("--source", default="Line0")
    p.add_argument("--region", default="")                    # "x,y,w,h"
    p.add_argument("--buffers", type=int, default=8)
    p.add_argument("--probe", action="store_true",
                   help="print 'DEVICES n' and exit (used for auto-detection)")
    args = p.parse_args()

    try:
        import gi
        gi.require_version("Aravis", "0.8")
        from gi.repository import Aravis
    except Exception as exc:  # noqa: BLE001
        if args.probe:
            print("DEVICES 0")
            return 0
        _err(f"FATAL: cannot import Aravis: {exc}")
        return 2

    import time

    def discover(retries=6, pause=0.4):
        """GigE discovery is intermittent on some hosts (broadcast races) — retry
        until a device appears."""
        n = 0
        for _ in range(retries):
            try:
                Aravis.update_device_list()
                n = Aravis.get_n_devices()
            except Exception:  # noqa: BLE001
                n = 0
            if n > 0:
                return n
            time.sleep(pause)
        return n

    if args.probe:
        print(f"DEVICES {discover()}")
        return 0

    try:
        n = discover()
        if n == 0:
            _err("FATAL: no GigE Vision cameras found")
            return 3
        device_id = args.device_id or Aravis.get_device_id(min(args.device_index, n - 1))
        cam = Aravis.Camera.new(device_id)
    except Exception as exc:  # noqa: BLE001
        _err(f"FATAL: open failed: {exc}")
        return 4

    def _safe(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return None

    _safe(lambda: cam.set_exposure_time_auto(Aravis.Auto.OFF))
    _safe(lambda: cam.set_exposure_time(args.exposure))
    _safe(lambda: cam.set_gain_auto(Aravis.Auto.OFF))
    _safe(lambda: cam.set_gain(args.gain))
    # the camera may default to SingleFrame (one frame per start) — force
    # Continuous so the stream keeps delivering frames
    _safe(lambda: cam.set_acquisition_mode(Aravis.AcquisitionMode.CONTINUOUS))
    _safe(lambda: cam.gv_auto_packet_size())  # negotiate a safe packet size for the link
    if args.fps:
        _safe(lambda: cam.set_frame_rate(args.fps))
    if args.region:
        try:
            x, y, w, h = (int(v) for v in args.region.split(","))
            _safe(lambda: cam.set_region(x, y, w, h))
        except ValueError:
            pass
    software = args.trigger == "software"
    if args.trigger == "continuous":
        _safe(lambda: cam.clear_triggers())
    elif software:
        _safe(lambda: cam.set_trigger("Software"))
    else:
        _safe(lambda: cam.set_trigger(args.source))

    try:
        stream = cam.create_stream(None, None)
        # macOS GigE: a large socket buffer + packet resend avoids the stream
        # overflow that otherwise drops ~100% of a continuous feed
        _safe(lambda: stream.set_property("socket-buffer-size", 16 * 1024 * 1024))
        _safe(lambda: stream.set_property("packet-resend", Aravis.GvStreamPacketResend.ALWAYS))
        payload = _safe(lambda: cam.get_payload()) or 0
        for _ in range(args.buffers):
            stream.push_buffer(Aravis.Buffer.new_allocate(payload))
        cam.start_acquisition()
    except Exception as exc:  # noqa: BLE001
        _err(f"FATAL: stream start failed: {exc}")
        return 5

    _err("READY")  # the app waits for this line before grabbing
    out = sys.stdout.buffer
    try:
        while True:
            if software:
                _safe(lambda: cam.software_trigger())
            buf = stream.timeout_pop_buffer(1_000_000)  # 1 s
            if buf is None:
                continue
            try:
                if buf.get_status() != Aravis.BufferStatus.SUCCESS:
                    continue
                w = int(buf.get_image_width())
                h = int(buf.get_image_height())
                pixel = int(buf.get_image_pixel_format())
                data = bytes(buf.get_data())
                out.write(MAGIC + struct.pack(">IIII", w, h, pixel, len(data)) + data)
                out.flush()
            finally:
                stream.push_buffer(buf)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    finally:
        _safe(lambda: cam.stop_acquisition())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
