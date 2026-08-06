"""Encrypted ONNX models — protecting the trained-model IP.

The models are the asset a competitor cannot recreate without the data flywheel,
so they ship encrypted (``<model>.onnx.enc``) and are decrypted **in memory
only** — the plaintext never touches disk. onnxruntime accepts a bytes buffer,
which is the pattern its own maintainers recommend for model protection.

Container (little-endian):

    b"VISM1"  | key_id (32B, utf-8 padded) | nonce (12B) | AES-256-GCM ciphertext

The key is derived per customer:

    key = HKDF-SHA256(master_secret, salt=license_id, info="vis-model:"+name)

so every customer's model file is a distinct ciphertext. Combined with a canary
embedded at build time, a leaked model identifies the customer it came from.

Honest limitation (documented, not hidden): on any interpreter the key and the
decrypted buffer exist in process memory, so this stops file copying, not a
determined attacker with a debugger. It is one layer — the binary build
(Nuitka), the signed license, and the support/AMC relationship are the others.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

MAGIC = b"VISM1"
_KEY_ID_LEN = 32
_NONCE_LEN = 12
ENC_SUFFIX = ".enc"


class ModelDecryptError(RuntimeError):
    """Encrypted model could not be opened with this installation's key."""


def _hkdf(master: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(master)


def _master_secret() -> bytes:
    """Build-time secret. Compiled into the binary for release builds (Nuitka
    embeds constants); VIS_MODEL_MASTER_KEY overrides for dev/CI."""
    env = os.environ.get("VIS_MODEL_MASTER_KEY")
    if env:
        return env.encode("utf-8")
    return _BUILD_MASTER_SECRET


# Replaced at build time by the release pipeline. Empty in source so the repo
# never contains a production key.
_BUILD_MASTER_SECRET = b""


def derive_key(license_id: str, model_name: str, master: bytes | None = None) -> bytes:
    master = master if master is not None else _master_secret()
    if not master:
        raise ModelDecryptError(
            "no model master secret in this build (set VIS_MODEL_MASTER_KEY for "
            "development builds)."
        )
    return _hkdf(master, license_id.encode("utf-8"), b"vis-model:" + model_name.encode("utf-8"))


def encrypt_model(
    plaintext: bytes, license_id: str, model_name: str, master: bytes | None = None
) -> bytes:
    """VENDOR-SIDE: produce a per-customer encrypted model container."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = derive_key(license_id, model_name, master)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, MAGIC)
    key_id = license_id.encode("utf-8")[:_KEY_ID_LEN].ljust(_KEY_ID_LEN, b"\x00")
    return MAGIC + key_id + nonce + ct


def is_encrypted(path: Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with path.open("rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except Exception:
        return False


def decrypt_model(blob: bytes, model_name: str, master: bytes | None = None) -> bytes:
    """Decrypt a container in memory. The key_id in the header names the license
    the file was issued to, so a file from another site fails with a clear
    message instead of a crypto error."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    header = len(MAGIC) + _KEY_ID_LEN + _NONCE_LEN
    if len(blob) < header or blob[: len(MAGIC)] != MAGIC:
        raise ModelDecryptError(f"{model_name}: not a VIS encrypted model container")
    key_id = blob[len(MAGIC) : len(MAGIC) + _KEY_ID_LEN].rstrip(b"\x00").decode("utf-8", "replace")
    nonce = blob[len(MAGIC) + _KEY_ID_LEN : header]
    try:
        key = derive_key(key_id, model_name, master)
        return AESGCM(key).decrypt(nonce, blob[header:], MAGIC)
    except InvalidTag as exc:
        raise ModelDecryptError(
            f"{model_name} was issued to license '{key_id}' and cannot be opened "
            "by this installation. Models are licensed per customer — request a "
            "model package for this site."
        ) from exc


def load_model_bytes(path: Path) -> bytes:
    """Read a model for onnxruntime, transparently decrypting ``.enc`` files.
    Plain ``.onnx`` files pass through (development and customer fine-tunes)."""
    path = Path(path)
    blob = path.read_bytes()
    if blob[: len(MAGIC)] == MAGIC:
        name = path.name[: -len(ENC_SUFFIX)] if path.name.endswith(ENC_SUFFIX) else path.name
        log.info("decrypting licensed model %s", name)
        return decrypt_model(blob, name)
    return blob


def resolve_model_path(path: Path) -> Path | None:
    """Given ``…/m.onnx``, return it, or its ``…/m.onnx.enc`` sibling, or None."""
    path = Path(path)
    if path.is_file():
        return path
    enc = path.with_name(path.name + ENC_SUFFIX)
    return enc if enc.is_file() else None
