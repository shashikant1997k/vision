#!/usr/bin/env python3
"""Download the PP-OCRv4 ONNX models (much more accurate than the bundled
PP-OCRv3 mobile) into the app data dir, where the OCR engine auto-discovers them.

Usage:
    python scripts/fetch_ocr_models.py            # v4 mobile rec (balanced, ~15MB)
    python scripts/fetch_ocr_models.py --server   # v4 server rec (most accurate, ~95MB)

The line PC runs fully offline afterwards. Override the location with
VIS_OCR_MODEL_DIR, or point VIS_OCR_DET_MODEL / VIS_OCR_REC_MODEL at specific files.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4"
FILES = {
    "det.onnx": f"{BASE}/ch_PP-OCRv4_det_infer.onnx",
    "rec.onnx": f"{BASE}/ch_PP-OCRv4_rec_infer.onnx",
}
SERVER_REC = f"{BASE}/ch_PP-OCRv4_rec_server_infer.onnx"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true", help="use the larger, most-accurate server recogniser")
    parser.add_argument("--dest", default=str(Path.home() / ".vision-inspection" / "models" / "ppocrv4"))
    args = parser.parse_args()

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = dict(FILES)
    if args.server:
        files["rec.onnx"] = SERVER_REC

    for name, url in files.items():
        target = dest / name
        print(f"Downloading {name} <- {url}")
        urllib.request.urlretrieve(url, target)
        print(f"  saved {target} ({target.stat().st_size // 1024} KB)")
    print(f"\nDone. OCR will auto-use these from {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
