"""Model-file integrity for the ONNX readers (GMP / 21 CFR Part 11).

A model file is validated configuration: the app must know *which* model made a
decision and refuse silently-swapped or corrupted files. Each shipped model may
carry two optional sidecars next to the ``.onnx``:

- ``<model>.sha256``     — hex digest of the .onnx (integrity manifest)
- ``<model>.meta.json``  — inference metadata, e.g. ``{"img_w": 256}``

Behaviour:
- sidecar present + hash matches   -> OK (fingerprint logged)
- sidecar present + hash mismatch  -> ALWAYS raises (corrupt/tampered file)
- sidecar absent                   -> strict mode raises, dev mode warns

Strict mode is on when ``VIS_MODEL_STRICT=1`` (set this on the line PC).
``fingerprint()`` is cheap to call repeatedly (digest cached by mtime/size).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_CACHE: dict[tuple[str, float, int], str] = {}


def strict_mode() -> bool:
    return os.environ.get("VIS_MODEL_STRICT", "").strip() in ("1", "true", "yes")


def sha256_of(path: Path) -> str:
    """Digest of a file, cached by (path, mtime, size)."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_mtime, stat.st_size)
    if key not in _CACHE:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _CACHE[key] = h.hexdigest()
    return _CACHE[key]


def verify_model(model_path: Path, *, what: str = "model") -> str:
    """Verify ``model_path`` against its ``.sha256`` sidecar and return the
    digest. Raises on mismatch (always) or on a missing sidecar in strict mode."""
    model_path = Path(model_path)
    digest = sha256_of(model_path)
    sidecar = model_path.with_suffix(model_path.suffix + ".sha256")
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="utf-8").split()[0].strip().lower()
        if digest.lower() != expected:
            raise RuntimeError(
                f"{what} integrity FAILURE: {model_path.name} sha256 {digest[:16]}… "
                f"does not match manifest {expected[:16]}… — the file was replaced "
                "or corrupted. Restore the validated model."
            )
        log.info("%s integrity OK: %s sha256=%s", what, model_path.name, digest[:16])
    elif strict_mode():
        raise RuntimeError(
            f"{what} integrity: no manifest ({sidecar.name}) next to "
            f"{model_path.name} and VIS_MODEL_STRICT is set. Deploy the model "
            "with its .sha256 sidecar."
        )
    else:
        log.warning(
            "%s %s has no .sha256 manifest (dev mode: allowed). sha256=%s",
            what, model_path.name, digest[:16],
        )
    return digest


def model_meta(model_path: Path) -> dict:
    """Optional ``<model>.meta.json`` sidecar (e.g. {"img_w": 256}); {} if absent."""
    meta = Path(model_path).with_suffix(".meta.json")
    if meta.is_file():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except Exception as exc:
            if strict_mode():
                raise RuntimeError(f"unreadable model metadata {meta.name}: {exc}") from exc
            log.warning("ignoring unreadable model metadata %s: %s", meta.name, exc)
    return {}
