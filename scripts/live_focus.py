"""Live camera preview for focusing/lighting — a reliable replacement for the
GTK arv-viewer on macOS. Native Qt (works on macOS), pulls frames from the
GigE camera through the same out-of-process Aravis worker the app uses.

Shows the live feed plus a brightness reading and a SHARPNESS score (variance of
Laplacian — turn the focus ring to MAXIMISE it). Run with the project venv:

    cd ~/Personal/camera
    .venv/bin/python scripts/live_focus.py            # auto exposure defaults
    .venv/bin/python scripts/live_focus.py --exposure 12000 --gain 2
"""

from __future__ import annotations

import argparse
import sys

import numpy as np


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exposure", type=float, default=10000.0)
    p.add_argument("--gain", type=float, default=1.0)
    p.add_argument("--device-index", type=int, default=0)
    args = p.parse_args()

    import cv2
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QImage, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from vis.camera.aravis_proc import AravisProcessCamera
    from vis.camera.settings import CameraSettings

    settings = CameraSettings(exposure_us=int(args.exposure), gain_db=args.gain, frame_rate=15.0)
    cam = AravisProcessCamera("focus", device_index=args.device_index, settings=settings)
    try:
        cam.open()
    except Exception as exc:  # noqa: BLE001
        print(f"Camera open failed: {exc}")
        return 1

    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("Live focus — maximise the sharpness number, then close")
    layout = QVBoxLayout(win)
    image_label = QLabel("waiting for frames…")
    image_label.setAlignment(Qt.AlignCenter)
    stats = QLabel("")
    stats.setStyleSheet("font: 16px 'Menlo'; padding: 6px")
    layout.addWidget(image_label, 1)
    layout.addWidget(stats)
    win.resize(900, 760)
    win.show()

    def tick():
        frame = cam.grab()
        if frame is None:
            return
        img = frame.image
        gray = img[..., 0] if img.ndim == 3 else img
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
        mean = float(gray.mean())
        # downscale for display
        h, w = gray.shape[:2]
        scale = min(880 / w, 660 / h, 1.0)
        disp = cv2.resize(img, (int(w * scale), int(h * scale)))
        rgb = np.ascontiguousarray(disp[..., ::-1] if disp.ndim == 3 else disp)
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.shape[1] * 3, QImage.Format_RGB888) \
            if rgb.ndim == 3 else QImage(rgb.data, w, h, w, QImage.Format_Grayscale8)
        image_label.setPixmap(QPixmap.fromImage(qimg))
        verdict = "TOO DARK" if mean < 25 else "bright/clipping" if mean > 230 else "exposure OK"
        stats.setText(f"{w}x{h}   brightness {mean:5.1f} ({verdict})   "
                      f"SHARPNESS {sharp:8.0f}  ← turn focus ring to maximise")

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(66)  # ~15 fps
    try:
        return app.exec()
    finally:
        cam.close()


if __name__ == "__main__":
    raise SystemExit(main())
