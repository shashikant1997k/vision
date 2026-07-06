"""``vis_ocr`` text reader — the in-house CRNN/CTC recogniser (ocr-trainer ONNX).

Drop-in provider for the reader seam (see ``readers.py``). It loads the ONNX
exported by the ocr-trainer project (``vis_ocr.onnx`` + sidecar ``charset.txt``),
runs onnxruntime on the field crop, and greedy-CTC-decodes to ``(text,
confidence)``. The tool layer applies the charset/regex/confusables constraints
on top, exactly as it does for the builtin reader.

Enable with ``VIS_TEXT_READER=vis_ocr`` (or recipe/tool ``reader="vis_ocr"``).
The model is located via ``VIS_OCR_MODEL`` or a few default paths; ``charset.txt``
must sit next to the ``.onnx``. Registration is skipped silently if onnxruntime
or the model file is absent, so importing this module is always safe.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

IMG_H = 32
IMG_W = 256


def _candidate_model_paths() -> list[Path]:
    paths = []
    env = os.environ.get("VIS_OCR_MODEL")
    if env:
        paths.append(Path(env))
    dirs = [
        Path.home() / ".vision-inspection",                    # deployed location
        Path.home() / "Personal/camera/ocr-trainer/model",     # Mac dev layout
        Path.home() / "camera/ocr-trainer/model",              # Linux VM layout
        Path.cwd() / "model",
    ]
    # prefer the OCR-A/B SVTR model, fall back to the older vis_ocr.onnx
    names = ["ocrab_svtr256.onnx", "vis_ocr.onnx"]
    for d in dirs:
        for n in names:
            paths.append(d / n)
    return paths


def _find_model() -> Path | None:
    for p in _candidate_model_paths():
        if p.is_file():
            return p
    return None


def _to_gray(image) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 3:
        # RGB (load_image convention) -> luminance
        arr = arr[..., :3].astype(np.float32)
        return (0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2])
    return arr.astype(np.float32)


def _preprocess(image) -> np.ndarray:
    """Grayscale, height 32, left-aligned on a white canvas, normalised [-1, 1].
    Mirrors ocrtrainer.dataset / evaluate exactly so the model sees its training
    distribution."""
    import cv2

    gray = _to_gray(image)
    h, w = gray.shape[:2]
    if h < 1 or w < 1:
        gray = np.full((IMG_H, IMG_W), 255.0, np.float32)
        h, w = gray.shape
    new_w = max(1, min(IMG_W, int(round(w * IMG_H / h))))
    resized = cv2.resize(gray.astype(np.uint8), (new_w, IMG_H), interpolation=cv2.INTER_AREA)
    canvas = np.full((IMG_H, IMG_W), 255, np.uint8)
    canvas[:, :new_w] = resized
    x = canvas.astype(np.float32) / 127.5 - 1.0
    return x[None, None]  # (1, 1, 32, W)


def _softmax_lastaxis(logits: np.ndarray) -> np.ndarray:
    m = logits.max(axis=-1, keepdims=True)
    e = np.exp(logits - m)
    return e / e.sum(axis=-1, keepdims=True)


class VisOcrReader:
    """Lazily-loaded CRNN/CTC ONNX recogniser bound to a model + charset."""

    def __init__(self, model_path: Path) -> None:
        self.model_path = Path(model_path)
        self._sess = None
        self._itos: list[str] = []

    def _ensure(self) -> None:
        if self._sess is not None:
            return
        import onnxruntime as ort

        # per-model sidecar (<model>.charset.txt) wins, else shared charset.txt
        per = self.model_path.with_name(self.model_path.stem + ".charset.txt")
        charset_path = per if per.is_file() else self.model_path.with_name("charset.txt")
        charset = charset_path.read_text(encoding="utf-8").strip("\n")
        self._itos = ["<blank>"] + list(charset)
        self._sess = ort.InferenceSession(
            str(self.model_path), providers=["CPUExecutionProvider"]
        )
        self._input = self._sess.get_inputs()[0].name

    def _decode(self, logits: np.ndarray) -> tuple[str, float]:
        # logits: (T, C) for a single sample
        probs = _softmax_lastaxis(logits)
        idx = logits.argmax(axis=-1)
        chars, confs, prev = [], [], 0
        for t, i in enumerate(idx):
            if i != prev and i != 0:
                chars.append(self._itos[i])
                confs.append(float(probs[t, i]))
            prev = i
        text = "".join(chars)
        conf = float(np.mean(confs)) if confs else 0.0
        return text, conf

    def __call__(self, image, config=None) -> tuple[str, float]:
        self._ensure()
        x = _preprocess(image)
        out = self._sess.run(None, {self._input: x})[0]  # (T, 1, C)
        logits = np.asarray(out)[:, 0, :]
        return self._decode(logits)


def register(force: bool = False) -> bool:
    """Register the ``vis_ocr`` reader if onnxruntime + a model file are present.
    Returns True if registered. Safe to call at import time."""
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    model = _find_model()
    if model is None and not force:
        return False
    from .readers import register_text_reader

    register_text_reader("vis_ocr", VisOcrReader(model or _candidate_model_paths()[0]))
    return True
