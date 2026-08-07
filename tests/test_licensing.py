"""Licensing: signature verification, node-locking, expiry, pack gating, model crypto."""

from __future__ import annotations

import base64
import json
from datetime import date

import pytest

from vis.licensing import license as lic_mod
from vis.licensing.license import License, LicenseError, load_license, sign_license, verify_document
from vis.licensing.model_crypto import ModelDecryptError, decrypt_model, encrypt_model
from vis.licensing.packs import PACKS, pack_for_tool, tool_allowed

MASTER = b"unit-test-master-secret"


@pytest.fixture
def vendor_keys():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    return {
        "private": base64.b64encode(
            key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        ).decode(),
        "public": base64.b64encode(
            key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode(),
    }


@pytest.fixture
def signed(vendor_keys, monkeypatch):
    """A genuine license document, with the vendor public key installed."""
    monkeypatch.setenv("VIS_LICENSE_PUBKEY", vendor_keys["public"])
    payload = {
        "license_id": "TEST-0001",
        "customer": "Test Pharma",
        "packs": ["pharma-ocv", "codes"],
        "machines": [],
        "seats": 1,
        "issued": "2026-01-01",
        "expires": None,
        "grace_days": 14,
    }
    return sign_license(payload, vendor_keys["private"]), payload


def test_genuine_license_verifies(signed):
    doc, payload = signed
    assert verify_document(doc) == payload


def test_edited_payload_is_rejected(signed):
    """The whole point: a customer cannot grant themselves extra packs."""
    doc, _ = signed
    doc["payload"]["packs"].append("sorting")
    with pytest.raises(LicenseError, match="INVALID"):
        verify_document(doc)


def test_signature_from_another_key_is_rejected(signed, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat,
    )

    doc, payload = signed
    rogue = Ed25519PrivateKey.generate()
    forged = sign_license(
        payload,
        base64.b64encode(
            rogue.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        ).decode(),
    )
    with pytest.raises(LicenseError, match="INVALID"):
        verify_document(forged)


def test_load_from_file(tmp_path, signed):
    doc, _ = signed
    path = tmp_path / "vision.lic"
    path.write_text(json.dumps(doc))
    lic = load_license(path)
    assert lic.license_id == "TEST-0001"
    assert lic.has_pack("pharma-ocv") and not lic.has_pack("sorting")


def test_missing_license_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("VIS_LICENSE", str(tmp_path / "nope.lic"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(lic_mod, "_DEFAULT_NAMES", ())
    with pytest.raises(LicenseError, match="no license file"):
        load_license()


# ---- expiry / grace ------------------------------------------------------
@pytest.mark.parametrize(
    "today,allowed",
    [(date(2026, 7, 20), True),    # before expiry
     (date(2026, 8, 10), True),    # inside grace
     (date(2026, 8, 20), False)],  # past grace
)
def test_expiry_grace_window(today, allowed):
    lic = License("X", "c", frozenset(["pharma-ocv"]), expires="2026-08-01", grace_days=14)
    if allowed:
        lic.check_valid(today=today)
    else:
        with pytest.raises(LicenseError, match="expired"):
            lic.check_valid(today=today)


def test_perpetual_license_never_expires():
    lic = License("X", "c", frozenset(["pharma-ocv"]), expires=None)
    lic.check_valid(today=date(2099, 1, 1))
    assert lic.days_remaining() is None


# ---- node locking --------------------------------------------------------
def test_node_lock_matches_and_rejects():
    lic = License("X", "c", frozenset(), machines=("aa" * 32,))
    lic.check_valid(machine="aa" * 32)
    with pytest.raises(LicenseError, match="node-locked"):
        lic.check_valid(machine="bb" * 32)


def test_no_machines_means_not_node_locked():
    License("X", "c", frozenset()).check_valid(machine="anything")


def test_fingerprint_is_stable_and_hex():
    from vis.licensing.fingerprint import machine_fingerprint

    a, b = machine_fingerprint(), machine_fingerprint()
    assert a == b and len(a) == 64
    int(a, 16)  # hex


# ---- capability packs ----------------------------------------------------
def test_pack_lookup_for_known_tool():
    assert pack_for_tool("code_verify").key == "codes"
    assert pack_for_tool("ocv_text").key == "pharma-ocv"


def test_tool_gating_follows_license(monkeypatch):
    monkeypatch.setattr("vis.licensing.packs.has_pack", lambda p: p == "pharma-ocv")
    assert tool_allowed("ocv_text")
    assert not tool_allowed("code_verify")
    assert tool_allowed("presence")      # core tool: always allowed


def test_unknown_tool_fails_open(monkeypatch):
    """An engine update must never brick an existing validated recipe."""
    monkeypatch.setattr("vis.licensing.packs.has_pack", lambda p: False)
    assert tool_allowed("some_future_tool")


def test_every_pack_has_title_and_description():
    for key, pack in PACKS.items():
        assert pack.key == key and pack.title and pack.description


def test_issue_all_expands_to_one_licence_for_the_whole_product(tmp_path, capsys):
    """`--packs all` sells the product as one licence instead of capability by
    capability — and must write out the EXPANDED list, so the licence names what
    it grants rather than silently widening when a new pack ships."""
    from vis.licensing.issue import main as issue_main

    keyfile = tmp_path / "keys.json"
    issue_main(["keygen", "--out", str(keyfile)])
    out = tmp_path / "all.lic"
    rc = issue_main(["issue", "--keyfile", str(keyfile), "--customer", "Plant X",
                     "--packs", "all", "--out", str(out)])
    assert rc == 0

    granted = json.loads(out.read_text())["payload"]["packs"]
    assert set(granted) == set(PACKS)
    assert "all" not in granted            # expanded, not stored as a wildcard


def test_issue_rejects_an_unknown_pack(tmp_path):
    from vis.licensing.issue import main as issue_main

    keyfile = tmp_path / "keys.json"
    issue_main(["keygen", "--out", str(keyfile)])
    rc = issue_main(["issue", "--keyfile", str(keyfile), "--customer", "X",
                     "--packs", "codes,not-a-pack", "--out", str(tmp_path / "x.lic")])
    assert rc == 2


# ---- model encryption ----------------------------------------------------
def test_encrypt_decrypt_roundtrip():
    plain = b"\x08onnx-model-bytes" * 100
    blob = encrypt_model(plain, "CPL-1", "m.onnx", MASTER)
    assert blob != plain
    assert decrypt_model(blob, "m.onnx", MASTER) == plain


def test_model_from_another_customer_is_useless():
    blob = encrypt_model(b"weights", "CPL-1", "m.onnx", MASTER)
    with pytest.raises(ModelDecryptError, match="issued to license"):
        decrypt_model(blob, "m.onnx", b"a-different-master-secret")


def test_wrong_model_name_fails():
    """Key is bound to the model name, so files can't be swapped between slots."""
    blob = encrypt_model(b"weights", "CPL-1", "ocr.onnx", MASTER)
    with pytest.raises(ModelDecryptError):
        decrypt_model(blob, "detector.onnx", MASTER)


def test_tampered_ciphertext_is_detected():
    blob = bytearray(encrypt_model(b"weights", "CPL-1", "m.onnx", MASTER))
    blob[-1] ^= 0xFF  # flip a bit in the AES-GCM tag/ciphertext
    with pytest.raises(ModelDecryptError):
        decrypt_model(bytes(blob), "m.onnx", MASTER)


def test_plain_onnx_passes_through(tmp_path):
    """Development models (unencrypted) still load."""
    from vis.licensing.model_crypto import load_model_bytes

    p = tmp_path / "dev.onnx"
    p.write_bytes(b"plain-onnx")
    assert load_model_bytes(p) == b"plain-onnx"
