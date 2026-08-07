#!/usr/bin/env python3
"""Stage the trained models into a built distribution folder.

    python packaging/stage_models.py                       # ocr-trainer -> dist/vis-hmi/model
    python packaging/stage_models.py --dist D:\\out\\vis-hmi --models D:\\ocr-trainer\\model

The PyInstaller spec deliberately does not bundle models: they are shipped per
customer and can be replaced without a rebuild. But a folder that an engineer is
supposed to copy to a line PC and just run has to arrive complete, so this puts
them beside ``vis-hmi.exe`` in ``model\\`` — the first directory the readers look
in when frozen.

Every file is copied with a ``.sha256`` sidecar. That is not decoration: the
readers refuse a model whose digest does not match its manifest, and the digest
list is the evidence an IQ needs to record which model made which decision.

Note this stages PLAINTEXT models — right for an internal or pilot line. For a
paid customer, run ``vis-license package`` instead, which encrypts each model to
that customer's licence.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST = ROOT / "dist" / "vis-hmi"
DEFAULT_MODELS = ROOT.parent / "ocr-trainer" / "model"

# The recogniser needs its charset sidecar; without it the reader cannot decode.
REQUIRED = [
    ("ocrab_svtr256.onnx", "SVTR/CTC text recogniser"),
    ("ocrab_svtr256.charset.txt", "recogniser charset (must match the model)"),
    ("textline_det.onnx", "YOLO text-line detector"),
]
OPTIONAL = [("charset.txt", "shared charset fallback")]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(src_dir: Path, dist: Path) -> int:
    if not dist.is_dir():
        sys.exit(f"no build folder at {dist} — run packaging/build_windows.py first")
    if not src_dir.is_dir():
        sys.exit(f"no model folder at {src_dir} — clone ocr-trainer beside this repo")

    out = dist / "model"
    out.mkdir(parents=True, exist_ok=True)

    missing = [n for n, _ in REQUIRED if not (src_dir / n).is_file()]
    if missing:
        sys.exit(f"missing required model files in {src_dir}: {', '.join(missing)}")

    staged = 0
    for name, what in REQUIRED + OPTIONAL:
        src = src_dir / name
        if not src.is_file():
            print(f"  - {name:<32} (absent, optional) — {what}")
            continue
        shutil.copy2(src, out / name)
        digest = sha256_of(out / name)
        # only .onnx files are integrity-checked at load, but hashing every file
        # keeps the IQ record complete
        (out / f"{name}.sha256").write_text(digest + "\n", encoding="utf-8")
        print(f"  + {name:<32} {digest[:16]}…  {what}")
        staged += 1

    print(f"\n  staged {staged} files into {out}")
    return 0


def refresh_manifests(model_dir: Path) -> int:
    """Rewrite the .sha256 sidecars next to the models, in place.

    A digest that no longer matches its model is ALWAYS fatal — that is the
    point of the manifest — so after retraining and dropping in a new .onnx the
    sidecar has to be regenerated or the reader refuses to load it.
    """
    if not model_dir.is_dir():
        sys.exit(f"no model folder at {model_dir}")
    count = 0
    for onnx in sorted(model_dir.glob("*.onnx")):
        digest = sha256_of(onnx)
        onnx.with_suffix(onnx.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
        print(f"  {onnx.name:32} {digest[:16]}…")
        count += 1
    print(f"\n  refreshed {count} manifest(s) in {model_dir}")
    print("  A changed model is a change-control event: record the new digest.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default=str(DEFAULT_DIST), help="built distribution folder")
    ap.add_argument("--models", default=str(DEFAULT_MODELS), help="ocr-trainer model folder")
    ap.add_argument("--refresh-manifests", action="store_true",
                    help="rewrite the .sha256 sidecars in the model folder itself "
                         "(do this after retraining), then exit")
    args = ap.parse_args()
    if args.refresh_manifests:
        print("Refreshing model manifests…")
        return refresh_manifests(Path(args.models))
    print("Staging models into the distribution folder…")
    return stage(Path(args.models), Path(args.dist))


if __name__ == "__main__":
    raise SystemExit(main())
