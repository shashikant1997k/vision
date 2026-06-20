"""Download the more accurate PP-OCRv4 ONNX models for the OCR engine.

rapidocr 1.2.x ships the older PP-OCRv3 *mobile* models, which read coded/
small print poorly. The engine (vis.tools.ocr) automatically prefers PP-OCRv4
models if it finds det.onnx + rec.onnx in:

    ~/.vision-inspection/models/ppocrv4/

This script fetches them there. Run on a machine with internet, then restart
the HMI. No code change needed — the engine picks them up on next start.

    python scripts/fetch_ppocrv4.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

DEST = Path.home() / ".vision-inspection" / "models" / "ppocrv4"

# RapidOCR's published PP-OCRv4 *server* ONNX (most accurate; the ch rec_server
# uses the default ppocr dictionary, so English letters + digits read well).
_MS_API = ("https://www.modelscope.cn/api/v1/models/RapidAI/RapidOCR/repo"
           "?Revision=master&FilePath={path}")
_MS_RESOLVE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/master/{path}"
_DET = "onnx/PP-OCRv4/det/ch_PP-OCRv4_det_server.onnx"
_REC = "onnx/PP-OCRv4/rec/ch_PP-OCRv4_rec_server.onnx"
SOURCES = {
    "det.onnx": [_MS_API.format(path=_DET), _MS_RESOLVE.format(path=_DET)],
    "rec.onnx": [_MS_API.format(path=_REC), _MS_RESOLVE.format(path=_REC)],
}


def _download(urls: list[str], dest: Path) -> bool:
    for url in urls:
        try:
            print(f"  trying {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "vision-inspection"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            if len(data) < 100_000:  # an ONNX model is MBs; a tiny body is an error page
                print(f"    too small ({len(data)} bytes) — skipping")
                continue
            dest.write_bytes(data)
            print(f"    saved {len(data) // 1024} KB -> {dest}")
            return True
        except Exception as exc:
            print(f"    failed: {exc}")
    return False


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, urls in SOURCES.items():
        print(f"{name}:")
        if not _download(urls, DEST / name):
            ok = False
            print(f"  COULD NOT FETCH {name}")
    if ok:
        print(f"\nDone. PP-OCRv4 models are in {DEST}. Restart the HMI to use them.")
        return 0
    print(
        "\nSome models could not be downloaded automatically. Download the "
        "PP-OCRv4 det + rec ONNX models manually (e.g. from the RapidOCR model "
        f"repo) and place them as det.onnx and rec.onnx in:\n  {DEST}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
