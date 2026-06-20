"""Report what camera the app is actually talking to — for a status display so
the operator can see at a glance whether a real camera is connected, which one,
its IP, and key config (vs. the simulator / a missing camera).
"""

from __future__ import annotations

import os


def _ip_str(value) -> str | None:
    try:
        v = int(value)
        return ".".join(str((v >> s) & 0xFF) for s in (24, 16, 8, 0))
    except Exception:
        return None


def probe_camera_status(simulation: bool, cti_path: str | None = None,
                        read_live: bool = True) -> dict:
    """Return a status dict: mode (simulator/gige/none), connected (bool),
    vendor/model/serial/ip/pixel_format/width/height/trigger when available, and
    a human 'summary' string. `read_live=False` skips opening the device (use
    while inspection is running so we don't fight it for the camera)."""
    if simulation:
        return {"mode": "simulator", "connected": False,
                "summary": "Simulator — no physical camera"}
    cti = cti_path or os.environ.get("VIS_GENTL_CTI")
    if not cti:
        return {"mode": "none", "connected": False,
                "summary": "No GenTL producer set (VIS_GENTL_CTI)"}
    if not os.path.exists(cti):
        return {"mode": "gige", "connected": False,
                "summary": f"GenTL producer not found: {cti}"}
    try:
        from harvesters.core import Harvester
    except Exception as exc:
        return {"mode": "gige", "connected": False,
                "summary": f"harvesters not installed: {exc}"}

    bindir = os.path.dirname(cti)
    try:
        os.add_dll_directory(bindir)
    except Exception:
        pass
    os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")

    h = Harvester()
    try:
        h.add_file(cti)
        h.update()
        devs = h.device_info_list
        if not devs:
            return {"mode": "gige", "connected": False,
                    "summary": "No camera found — check power, cable & subnet"}
        d = devs[0]
        info = {
            "mode": "gige", "connected": True,
            "vendor": getattr(d, "vendor", "") or "",
            "model": getattr(d, "model", "") or "",
            "serial": getattr(d, "serial_number", "") or "",
        }
        if read_live:
            try:
                ia = h.create(0)
                try:
                    nm = ia.remote_device.node_map
                    try:
                        info["ip"] = _ip_str(nm.GevCurrentIPAddress.value)
                    except Exception:
                        pass
                    for key, feat in (("pixel_format", "PixelFormat"),
                                      ("width", "Width"), ("height", "Height"),
                                      ("trigger", "TriggerMode")):
                        try:
                            info[key] = getattr(nm, feat).value
                        except Exception:
                            pass
                finally:
                    ia.destroy()
            except Exception:
                info["busy"] = True  # in use (likely by a running inspection)
        head = f"{info['vendor']} {info['model']}".strip() or "Camera"
        bits = [head]
        if info.get("serial"):
            bits.append(f"SN {info['serial']}")
        if info.get("ip"):
            bits.append(f"@ {info['ip']}")
        if info.get("width") and info.get("height"):
            bits.append(f"{info['width']}×{info['height']}")
        if info.get("pixel_format"):
            bits.append(str(info["pixel_format"]))
        info["summary"] = "  ·  ".join(bits)
        return info
    finally:
        try:
            h.reset()
        except Exception:
            pass
