"""Out-of-process Aravis camera: the framing protocol + worker lifecycle,
tested with a fake worker (same interpreter) so no brew/camera is needed."""

import struct
import sys
import textwrap

import numpy as np
import pytest

from vis.camera.aravis_proc import MAGIC, AravisProcessCamera
from vis.camera.hikrobot import PIXEL_MONO8

# a fake worker: prints READY to stderr, then emits `n` mono8 frames to stdout
_FAKE_WORKER = textwrap.dedent("""
    import sys, struct, time
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sys.stderr.write("READY\\n"); sys.stderr.flush()
    out = sys.stdout.buffer
    for i in range(n):
        w, h, pixel = 8, 8, 0x01080001
        payload = bytes(range(64))
        out.write(b"VF01" + struct.pack(">IIII", w, h, pixel, len(payload)) + payload)
        out.flush()
    time.sleep(0.2)
""")

_FATAL_WORKER = 'import sys; sys.stderr.write("FATAL: no GigE Vision cameras found\\n"); sys.stderr.flush()'


def _cam(worker_code, *args):
    return AravisProcessCamera(
        "cam1", worker_cmd=[sys.executable, "-c", worker_code, *map(str, args)],
        ready_timeout_s=5.0,
    )


def test_reads_framed_frames():
    cam = _cam(_FAKE_WORKER, 3)
    cam.open()
    try:
        frames = [cam.grab() for _ in range(3)]
        assert all(f is not None for f in frames)
        assert frames[0].image.shape == (8, 8, 3)
        assert frames[0].image[0, 1, 0] == 1  # mono replicated
        assert [f.frame_id for f in frames] == [1, 2, 3]
    finally:
        cam.close()


def test_frames_iterator_stops_at_eof():
    cam = _cam(_FAKE_WORKER, 2)
    frames = list(cam.frames())  # worker emits 2 then exits -> iterator ends
    assert len(frames) == 2
    cam.close()


def test_fatal_worker_raises_on_open():
    cam = _cam(_FATAL_WORKER)
    with pytest.raises(RuntimeError, match="no GigE Vision cameras"):
        cam.open()


def test_worker_exit_before_ready_raises():
    cam = _cam("import sys; sys.exit(7)")
    with pytest.raises(RuntimeError, match="exited"):
        cam.open()


def test_resync_to_magic_after_garbage():
    # worker emits junk before the first valid frame -> reader resyncs to MAGIC
    worker = textwrap.dedent("""
        import sys, struct
        sys.stderr.write("READY\\n"); sys.stderr.flush()
        out = sys.stdout.buffer
        out.write(b"garbage-bytes-before-frame")
        out.write(b"VF01" + struct.pack(">IIII", 8, 8, 0x01080001, 64) + bytes(64))
        out.flush()
        import time; time.sleep(0.2)
    """)
    cam = _cam(worker)
    cam.open()
    try:
        frame = cam.grab()
        assert frame is not None and frame.image.shape == (8, 8, 3)
    finally:
        cam.close()


def test_to_numpy_pixel_formats():
    rgb = AravisProcessCamera._to_numpy(2, 1, 0x02180014, bytes([10, 20, 30, 40, 50, 60]))
    assert rgb.shape == (1, 2, 3) and tuple(rgb[0, 0]) == (10, 20, 30)
    with pytest.raises(RuntimeError, match="unsupported pixel format"):
        AravisProcessCamera._to_numpy(2, 2, 0x0110000A, bytes(8))


def test_header_struct_roundtrip():
    packed = MAGIC + struct.pack(">IIII", 640, 480, PIXEL_MONO8, 100)
    assert packed[:4] == MAGIC
    w, h, pixel, length = struct.unpack(">IIII", packed[4:])
    assert (w, h, pixel, length) == (640, 480, PIXEL_MONO8, 100)
    assert isinstance(np.uint8(), np.uint8)


def test_count_devices_via_real_worker():
    """Integration: the real worker --probe prints a device count (0 here, no
    camera). Skips if no Aravis-capable interpreter is installed."""
    from vis.camera.aravis_proc import count_devices, find_aravis_python

    if find_aravis_python() is None:
        pytest.skip("no Aravis-capable python on this host")
    assert count_devices() >= 0  # returns a number, doesn't crash the app process
