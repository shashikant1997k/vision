"""Text-line DETECTOR (YOLO ONNX) for the teach flow.

Finds the bounding boxes of every text line in an image, so the teach window can
turn ONE operator-drawn box into one OCV tool per line (and auto-read each with
the ``vis_ocr`` recogniser). Pure onnxruntime + numpy — no ultralytics runtime
dependency. Model ``textline_det.onnx`` is produced by the ocr-trainer project.

    from vis.tools.line_detector import get_line_detector
    det = get_line_detector()                 # None if model/onnxruntime absent
    boxes = det.detect(rgb_image)             # [(x, y, w, h, score), ...] top->bottom
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

INP = 640


def _candidate_paths() -> list[Path]:
    paths = []
    env = os.environ.get("VIS_DET_MODEL")
    if env:
        paths.append(Path(env))
    dirs = [Path.home() / ".vision-inspection",
            Path.home() / "Personal/camera/ocr-trainer/model",   # Mac dev layout
            Path.home() / "camera/ocr-trainer/model",            # Linux VM layout
            Path.cwd() / "model"]
    # parallel-repo layout: <parent of the camera project>/ocr-trainer/model
    try:
        dirs.append(Path(__file__).resolve().parents[3].parent / "ocr-trainer" / "model")
    except Exception:
        pass
    for d in dirs:
        paths.append(d / "textline_det.onnx")
    return paths


def _find_model() -> Path | None:
    for p in _candidate_paths():
        if p.is_file():
            return p
    return None


def _letterbox(img: np.ndarray, size: int = INP):
    import cv2

    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((size, size, 3), 114, np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh))
    return canvas, r, left, top


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0, xx2 - xx1); h = np.maximum(0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


class LineDetector:
    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self._sess = None

    def _ensure(self) -> None:
        if self._sess is not None:
            return
        import onnxruntime as ort

        self._sess = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])
        self._input = self._sess.get_inputs()[0].name

    def detect(self, image, conf: float = 0.4, iou: float = 0.45) -> list[tuple]:
        """image: RGB (or grayscale) ndarray. Returns [(x,y,w,h,score)] in image
        coordinates, sorted top-to-bottom."""
        import cv2

        self._ensure()
        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        elif arr.shape[2] == 4:
            arr = arr[..., :3]
        H, W = arr.shape[:2]
        lb, r, left, top = _letterbox(arr)
        x = (lb.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]   # (1,3,640,640) RGB
        out = np.squeeze(self._sess.run(None, {self._input: x})[0], 0).T  # (N, 4+nc)
        scores = out[:, 4]
        m = scores >= conf
        out, scores = out[m], scores[m]
        if len(out) == 0:
            return []
        cx, cy, bw, bh = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        boxes = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], 1)
        res = []
        for i in _nms(boxes, scores, iou):
            x1 = max(0, min(W, (boxes[i, 0] - left) / r)); y1 = max(0, min(H, (boxes[i, 1] - top) / r))
            x2 = max(0, min(W, (boxes[i, 2] - left) / r)); y2 = max(0, min(H, (boxes[i, 3] - top) / r))
            if x2 - x1 >= 3 and y2 - y1 >= 3:
                res.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1), float(scores[i])))
        res.sort(key=lambda b: b[1])
        return res


_DETECTOR = None


def get_line_detector():
    """Lazily build the detector; returns None if model/onnxruntime is absent."""
    global _DETECTOR
    if _DETECTOR is None:
        try:
            import onnxruntime  # noqa: F401
        except Exception:
            return None
        m = _find_model()
        if m is None:
            return None
        _DETECTOR = LineDetector(m)
    return _DETECTOR
