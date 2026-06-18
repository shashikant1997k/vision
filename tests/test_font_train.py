"""Auto-train OCV font from images: proportional segmentation, label matching,
and installing a trained font into the library."""

import base64

import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.fonts import FontRepository  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.tools.font_train import _best_line  # noqa: E402
from vis.tools.ocv_font import _segment_to_count  # noqa: E402


def _proportional_word():
    """A binary image of three blobs of UNEQUAL width with gaps (proportional)."""
    img = np.zeros((40, 200), np.uint8)
    img[8:32, 10:18] = 255    # narrow (like 'I')
    img[8:32, 40:80] = 255    # wide (like 'M')
    img[8:32, 110:130] = 255  # medium
    return img


def test_segment_to_count_respects_real_widths():
    boxes = _segment_to_count(_proportional_word(), 3)
    assert len(boxes) == 3
    xs = [b[0] for b in boxes]
    assert xs == sorted(xs)  # left-to-right
    widths = [b[2] for b in boxes]
    assert widths[1] > widths[0]  # the wide blob stays wider than the narrow one


def test_segment_merges_when_too_many_components():
    # 4 blobs but we want 3 -> the closest pair merges
    img = np.zeros((40, 200), np.uint8)
    for x in (10, 22, 80, 140):  # first two are close together
        img[8:32, x:x + 8] = 255
    boxes = _segment_to_count(img, 3)
    assert len(boxes) == 3


def test_segment_splits_when_too_few_components():
    # one wide touching blob, want 3
    img = np.zeros((40, 200), np.uint8)
    img[8:32, 20:170] = 255
    boxes = _segment_to_count(img, 3)
    assert len(boxes) == 3


def test_best_line_matches_by_confusable_overlap():
    lines = [
        ("MFG. 10/2025", (0, 10, 0, 100)),
        ("B.N0.TEST12345", (20, 30, 0, 200)),   # OCR slip 0 vs O
        ("noise xyz", (40, 50, 0, 50)),
    ]
    used = set()
    i, box = _best_line("B.No.TEST12345", lines, used)
    assert i == 1 and box == (20, 30, 0, 200)  # matched despite 0/O
    i2, _ = _best_line("MFG.10/2025", lines, {1})
    assert i2 == 0


def test_best_line_returns_none_when_no_match():
    lines = [("completely different", (0, 1, 0, 1))]
    i, box = _best_line("B.No.TEST12345", lines, set())
    assert i is None and box is None


def _glyph_b64():
    g = np.zeros((32, 24), np.uint8)
    g[5:27, 5:19] = 255
    ok, buf = cv2.imencode(".png", g)
    return base64.b64encode(buf.tobytes()).decode()


def test_seed_trained_font_install_and_replace(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    UserService(sf).seed_roles()
    repo = FontRepository(sf)

    glyphs = {"A": [_glyph_b64()], "0": [_glyph_b64(), _glyph_b64()]}
    fid = repo.seed_trained_font("Customer carton (TIJ)", "tij", glyphs, dot_kernel=0)
    assert fid > 0
    names = {f["name"]: f for f in repo.list_fonts()}
    assert "Customer carton (TIJ)" in names
    assert names["Customer carton (TIJ)"]["samples"] == 3

    # replace=True refreshes glyphs in place (same id)
    fid2 = repo.seed_trained_font("Customer carton (TIJ)", "tij", {"A": [_glyph_b64()]}, replace=True)
    assert fid2 == fid
    _, embedded, _ = repo.glyphs(fid)
    assert set(embedded.keys()) == {"A"}
