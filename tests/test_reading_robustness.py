"""Industry-grade robustness benchmark for the reading core (codes + OCR).

Simulates the degradations a real line produces — small codes from a wide FOV,
glare gradients off foil, faint low-contrast print, inverted polarity, motion
blur — and asserts the conditioning ladders still read them. These are the
failure modes observed on the actual Sun Pharma carton captures.
"""

import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("zxingcpp")
pytest.importorskip("qrcode")

import cv2  # noqa: E402
import qrcode  # noqa: E402

from vis.tools.decode import decode_first  # noqa: E402

PAYLOAD = "https://suntop300.pharmasecure.us/21/3B8YGKRUF"


def _qr(payload=PAYLOAD, box=8, border=4) -> np.ndarray:
    q = qrcode.QRCode(box_size=box, border=border)
    q.add_data(payload)
    q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white")
    return np.array(img.convert("L"), dtype=np.uint8)


def _on_scene(code: np.ndarray, scene_gray=200, pad=40) -> np.ndarray:
    h, w = code.shape
    scene = np.full((h + 2 * pad, w + 2 * pad), scene_gray, np.uint8)
    scene[pad:pad + h, pad:pad + w] = code
    return scene


def test_decodes_clean_code():
    assert decode_first(_on_scene(_qr())).text == PAYLOAD


def test_decodes_small_code():
    """Wide-FOV line: the code occupies a tiny part of the frame (~1.5 px/module).
    The upscale+sharpen rung must recover it."""
    small = cv2.resize(_qr(box=8), None, fx=0.18, fy=0.18, interpolation=cv2.INTER_AREA)
    assert decode_first(_on_scene(small)).ok


def test_decodes_low_contrast_code():
    """Faint print on foil: black modules at ~grey 120 on a 160 background."""
    code = _qr()
    faint = (160 - (255 - code.astype(np.int32)) * 40 // 255).astype(np.uint8)
    assert decode_first(_on_scene(faint, scene_gray=160)).ok


def test_decodes_code_under_glare_gradient():
    """A specular gradient washing out one side (the blown-out strip on the
    carton). Glare-clip + contrast rungs must recover it."""
    scene = _on_scene(_qr()).astype(np.float32)
    h, w = scene.shape
    gradient = np.linspace(0, 140, w, dtype=np.float32)[None, :]
    washed = np.clip(scene * 0.55 + gradient + 60, 0, 255).astype(np.uint8)
    assert decode_first(washed).ok


def test_decodes_blurred_code():
    """Slight defocus/motion blur."""
    blurred = cv2.GaussianBlur(_on_scene(_qr()), (5, 5), 1.4)
    assert decode_first(blurred).ok


def test_decodes_inverted_code():
    """White-on-black (laser-marked / DPM polarity)."""
    assert decode_first(255 - _on_scene(_qr())).ok


def test_no_decode_on_blank_returns_cleanly():
    blank = np.full((300, 300), 180, np.uint8)
    d = decode_first(blank)
    assert not d.ok and d.text == ""


# ---- OCR core under the same conditions ------------------------------------

def _text_img(text="B.NO.TEST12345", contrast=0, glare=False) -> np.ndarray:
    img = np.full((60, 30 + len(text) * 22, 3), 255, np.uint8)
    cv2.putText(img, text, (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    if contrast:  # lift blacks toward the background (faint print)
        g = img[..., 0].astype(np.int32)
        img = np.stack([np.clip(g + contrast, 0, 255).astype(np.uint8)] * 3, axis=-1)
    if glare:
        h, w = img.shape[:2]
        gradient = np.linspace(0, 90, w, dtype=np.float32)[None, :, None]
        img = np.clip(img.astype(np.float32) + gradient, 0, 255).astype(np.uint8)
    return img


def test_ocr_reads_clean_and_degraded_lines():
    pytest.importorskip("rapidocr_onnxruntime")
    from vis.tools.ocr import _match_key, recognize

    clean, conf = recognize(_text_img())
    assert _match_key(clean) == _match_key("B.NO.TEST12345") and conf > 0.7

    faint, _ = recognize(_text_img(contrast=120))
    glared, _ = recognize(_text_img(glare=True))
    # degraded lines must still resolve to the same normalized content
    assert _match_key(faint) == _match_key("B.NO.TEST12345")
    assert _match_key(glared) == _match_key("B.NO.TEST12345")
