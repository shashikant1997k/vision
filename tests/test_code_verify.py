"""Round-trip tests: render a real QR code, then decode + verify + grade it.

Uses `qrcode` to generate genuine codes (dev dependency) so we exercise the
real zxing-cpp decode path, not a stub.
"""

import numpy as np
import pytest

from vis.tools import build_tool

qrcode = pytest.importorskip("qrcode")


def _qr_image(text: str) -> np.ndarray:
    qr = qrcode.QRCode(border=4, box_size=8)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return np.array(img, dtype=np.uint8)


def test_decode_and_content_match_passes():
    text = "HELLO-LOT42"
    tool = build_tool("code_verify", "c1", {"gs1": False, "expected_data": text})
    result = tool.inspect(_qr_image(text))
    assert result.passed
    assert result.measured_value == text
    assert result.detail["grade"]["decode"] == "A"
    assert result.detail["grade"]["overall"] in {"A", "B"}


def test_content_mismatch_fails():
    tool = build_tool("code_verify", "c1", {"gs1": False, "expected_data": "RIGHT"})
    result = tool.inspect(_qr_image("WRONG"))
    assert not result.passed
    assert "mismatches" in result.detail


def test_gs1_field_verification():
    data = "0109506000134352" + "17" + "260101" + "10" + "LOT42"
    tool = build_tool(
        "code_verify",
        "c1",
        {"gs1": True, "expected_fields": {"gtin": "09506000134352", "batch": "LOT42"}},
    )
    result = tool.inspect(_qr_image(data))
    assert result.passed
    assert result.detail["fields"]["expiry"] == "260101"


def test_no_decode_grades_f():
    blank = np.full((60, 60, 3), 128, dtype=np.uint8)
    tool = build_tool("code_verify", "c1", {"expected_data": "X"})
    result = tool.inspect(blank)
    assert not result.passed
    assert result.detail["grade"]["overall"] == "F"
    assert result.detail["reason"] == "no_decode"
