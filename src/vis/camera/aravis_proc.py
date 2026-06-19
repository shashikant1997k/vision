"""Out-of-process Aravis camera — the reliable macOS path.

On macOS the Aravis Python bindings must run under the SAME toolchain as the
brew-installed aravis/glib; pip's PyGObject in an app venv typically segfaults.
So we run scripts/aravis_worker.py under a compatible interpreter (Homebrew's
python3) and read length-framed frames from its stdout. This also isolates the
app from a misbehaving binding: if the worker dies, only acquisition stops.

Same CameraDevice interface as every other source; the worker command is
injectable so the framing protocol is unit-tested with a fake worker.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np

from ..engine.frame import Frame
from .device import CameraDevice, CameraInfo
from .hikrobot import PIXEL_BGR8_PACKED, PIXEL_MONO8, PIXEL_RGB8_PACKED
from .settings import TriggerMode

MAGIC = b"VF01"
_HEADER = struct.Struct(">IIII")  # w, h, pixel, length


def find_aravis_python() -> str | None:
    """An interpreter that can import Aravis. VIS_ARAVIS_PYTHON overrides; else
    Homebrew's python3 (which shares glib with brew's aravis on macOS)."""
    explicit = os.environ.get("VIS_ARAVIS_PYTHON")
    if explicit and Path(explicit).exists():
        return explicit
    for cand in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                 shutil.which("python3")):
        if cand and Path(cand).exists() and Path(cand).resolve() != Path(sys.executable).resolve():
            return cand
    return None


def _worker_script() -> str:
    return str(Path(__file__).resolve().parents[3] / "scripts" / "aravis_worker.py")


def count_devices(timeout_s: float = 8.0) -> int:
    """Number of GigE Vision cameras Aravis can see (0 on any failure). Runs the
    worker's --probe under an Aravis-capable interpreter, so it never imports the
    binding into this process."""
    py = find_aravis_python()
    if py is None:
        return 0
    try:
        out = subprocess.run(
            [py, _worker_script(), "--probe"], capture_output=True, timeout=timeout_s, text=True
        )
        for line in out.stdout.splitlines():
            if line.startswith("DEVICES "):
                return int(line.split()[1])
    except Exception:
        return 0
    return 0


class AravisProcessCamera(CameraDevice):
    def __init__(
        self, camera_id: str, device_index: int = 0, device_id: str | None = None,
        settings=None, worker_cmd: list[str] | None = None, ready_timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            CameraInfo(id=camera_id, vendor="GigE Vision (Aravis worker)", interface="GigE Vision"),
            settings,
        )
        self.device_index = device_index
        self.device_id = device_id
        self._worker_cmd = worker_cmd
        self._ready_timeout = ready_timeout_s
        self._proc: subprocess.Popen | None = None
        self._frame_id = 0

    # ---- lifecycle ---------------------------------------------------------
    def _build_cmd(self) -> list[str]:
        if self._worker_cmd is not None:
            return list(self._worker_cmd)
        py = find_aravis_python()
        if py is None:
            raise RuntimeError(
                "No Aravis-capable Python found. Install Aravis (brew install aravis "
                "pygobject3) and/or set VIS_ARAVIS_PYTHON to that interpreter. "
                "See docs/19-mac-gige-setup.md."
            )
        s = self.settings
        trig = s.trigger.mode
        trigger = ("software" if trig == TriggerMode.SOFTWARE
                   else "continuous" if trig == TriggerMode.CONTINUOUS else "hardware")
        roi = s.sensor_roi
        cmd = [
            py, _worker_script(),
            "--exposure", str(float(s.exposure_us)), "--gain", str(float(s.gain_db)),
            "--fps", str(float(s.frame_rate)), "--trigger", trigger,
            "--source", s.trigger.source or "Line0",
        ]
        if self.device_id:
            cmd += ["--device-id", self.device_id]
        else:
            cmd += ["--device-index", str(self.device_index)]
        if roi.w and roi.h:
            cmd += ["--region", f"{roi.x},{roi.y},{roi.w},{roi.h}"]
        return cmd

    def _open_device(self) -> None:
        self._proc = subprocess.Popen(
            self._build_cmd(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
        # wait for the worker's READY line (or a FATAL error) on stderr
        deadline = threading.Event()
        timer = threading.Timer(self._ready_timeout, deadline.set)
        timer.daemon = True
        timer.start()
        try:
            while not deadline.is_set():
                line = self._proc.stderr.readline()
                if not line:
                    code = self._proc.poll()
                    raise RuntimeError(f"Aravis worker exited (code {code}) before READY")
                text = line.decode(errors="ignore").strip()
                if text == "READY":
                    return
                if text.startswith("FATAL"):
                    raise RuntimeError(f"Aravis worker: {text}")
            raise RuntimeError("Aravis worker did not become READY in time")
        finally:
            timer.cancel()

    def _close_device(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    # ---- acquisition --------------------------------------------------------
    def _read_exact(self, n: int) -> bytes | None:
        buf = b""
        stream = self._proc.stdout
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def grab(self) -> Frame | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        # resync to the magic marker
        magic = self._read_exact(4)
        if magic is None:
            return None
        while magic != MAGIC:
            nxt = self._read_exact(1)
            if nxt is None:
                return None
            magic = magic[1:] + nxt
        header = self._read_exact(_HEADER.size)
        if header is None:
            return None
        w, h, pixel, length = _HEADER.unpack(header)
        payload = self._read_exact(length)
        if payload is None:
            return None
        image = self._to_numpy(w, h, pixel, payload)
        self._frame_id += 1
        return Frame(self.info.id, self._frame_id, image, timestamp=float(self._frame_id))

    @staticmethod
    def _to_numpy(w, h, pixel, payload) -> np.ndarray:
        data = np.frombuffer(payload, dtype=np.uint8)
        if pixel == PIXEL_MONO8:
            return np.stack([data[: h * w].reshape(h, w)] * 3, axis=-1)
        if pixel in (PIXEL_RGB8_PACKED, PIXEL_BGR8_PACKED):
            rgb = data[: h * w * 3].reshape(h, w, 3)
            return rgb[..., ::-1].copy() if pixel == PIXEL_BGR8_PACKED else rgb.copy()
        raise RuntimeError(
            f"Aravis: unsupported pixel format 0x{pixel:08x} — set PixelFormat to Mono8 or RGB8."
        )
