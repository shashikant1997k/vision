"""Train an OCV font from the real carton photos in teachimage/ and install it
into the font library as "Sun Pharma carton (TIJ)".

Usage:
    python scripts/train_carton_font.py [IMAGE_DIR] [--db URL]

OCV reads by matching each character against templates of the ACTUAL print, so
this trains from your own line photos (PP-OCR locates the lines; the known
strings below provide correct labels). After running, the font appears in the
teach screen's "Verify Text (OCV) → Font" dropdown. Use a digits-only charset on
date/MRP fields to avoid look-alike confusions (6/G, 0/O).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The known printed lines on this carton (correct labels for training).
CARTON_LABELS = [
    "B.No.TEST12345",
    "MFG.10/2025",
    "EXP.10/2026",
    "M.R.P Rs.000.00",
    "Per XX Tablets",
    "INCL. OF ALL TAXES",
]
FONT_NAME = "Sun Pharma carton (TIJ)"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    image_dir = Path(args[0]) if args else Path("teachimage")
    db_url = None
    if "--db" in sys.argv:
        db_url = sys.argv[sys.argv.index("--db") + 1]
    db_url = db_url or os.environ.get("DATABASE_URL") or (
        f"sqlite:///{Path.home() / '.vision-inspection' / 'vis.db'}"
    )

    images = sorted(
        str(p) for p in image_dir.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp") and "copy" not in p.name.lower()
    )
    if not images:
        print(f"No images in {image_dir}")
        return 1
    print(f"Training from {len(images)} images in {image_dir} ...")

    from vis.tools.font_train import train_font_from_images

    # the carton is photographed sideways -> rotate 90° clockwise (k=-1) upright
    glyphs, stats = train_font_from_images(images, CARTON_LABELS, rotate_k=-1, dot_kernel=0)
    print(f"  images used: {stats['images']}  lines trained: {stats['lines_trained']}")
    print(f"  characters: {stats['chars']}  glyph samples: {stats['glyphs']}")
    if not glyphs:
        print("  no glyphs trained — check rotation / image quality")
        return 1

    from vis.db.base import init_db, make_engine, make_session_factory
    from vis.db.fonts import FontRepository

    engine = make_engine(db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    fid = FontRepository(sf).seed_trained_font(FONT_NAME, "tij", glyphs, dot_kernel=0)
    print(f"  installed font #{fid} '{FONT_NAME}' into {db_url}")

    # quick self-check: read back a date line with a digits charset
    from vis.camera.file_source import load_image
    from vis.tools.font_train import _best_line, _ocr_lines
    from vis.tools.ocv_font import read_text
    import numpy as np

    img = np.rot90(load_image(images[0]), k=-1)
    lines = _ocr_lines(img)
    _i, box = _best_line("EXP.10/2026", lines, set())
    if box:
        y0, y1, x0, x1 = box
        crop = img[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8]
        text, score = read_text(crop, glyphs, charset="0123456789./EXP", min_char_score=0.3)
        print(f"  self-check read of EXP line: {text!r} (score {score:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
