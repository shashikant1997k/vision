"""OCV font library: built-in starter fonts, training (segment → annotate →
add samples), and the train→read loop with the per-character matcher."""

import base64

import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from vis.db.base import init_db, make_engine, make_session_factory  # noqa: E402
from vis.db.fonts import FontRepository  # noqa: E402
from vis.db.users import UserService  # noqa: E402
from vis.tools import build_tool  # noqa: E402
from vis.tools.fontgen import builtin_fonts, segment_sample  # noqa: E402
from vis.tools.ocv_font import read_text  # noqa: E402


def _setup(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    sf = make_session_factory(engine)
    users = UserService(sf)
    users.seed_roles()
    eng = users.create_user("eng", "Secret123", roles=("engineer",))
    op = users.create_user("op", "Secret123", roles=("operator",))
    return sf, eng, op


def _compose(glyphs: dict, text: str, cell=44, pad=8):
    """Compose an image of `text` from a font's glyph templates (black on white),
    like a coder printing those exact characters."""
    h, w = 36, 28
    canvas = np.full((h + 2 * pad, cell * len(text) + 2 * pad), 255, np.uint8)
    for i, ch in enumerate(text):
        template = base64.b64decode(glyphs[ch][0])
        glyph = cv2.imdecode(np.frombuffer(template, np.uint8), cv2.IMREAD_GRAYSCALE)
        glyph = cv2.resize(glyph, (w, h), interpolation=cv2.INTER_AREA)
        x = pad + i * cell
        region = canvas[pad : pad + h, x : x + w]
        region[glyph > 64] = 0  # dark print on a light substrate
    return np.stack([canvas] * 3, axis=-1)


def test_builtin_fonts_generated():
    fonts = builtin_fonts()
    names = {f["name"] for f in fonts}
    assert any("5×7" in n for n in names) and any("Solid" in n for n in names)
    for f in fonts:
        assert f["glyphs"].get("A") and f["glyphs"].get("0")


def test_repository_seeds_builtins_idempotently(tmp_path):
    sf, eng, _ = _setup(tmp_path)
    repo = FontRepository(sf)
    repo.ensure_builtins()
    n = len(repo.list_fonts())
    repo.ensure_builtins()
    assert len(repo.list_fonts()) == n >= 3
    fid = repo.list_fonts()[0]["id"]
    name, glyphs, kernel = repo.glyphs(fid)
    assert glyphs and isinstance(kernel, int)


def test_rbac_on_font_training(tmp_path):
    sf, eng, op = _setup(tmp_path)
    repo = FontRepository(sf)
    with pytest.raises(PermissionError):
        repo.create_font(op, "X", "cij")
    fid = repo.create_font(eng, "Line3 Videojet 7x5", "cij", dot_kernel=5)
    with pytest.raises(PermissionError):
        repo.add_samples(op, fid, [("A", "x")])


def test_builtin_dot_font_reads_dot_printed_text(tmp_path):
    """The CIJ starter font must read text printed in its own dot style."""
    dot = next(f for f in builtin_fonts() if "5×7" in f["name"])
    image = _compose(dot["glyphs"], "2024")
    tool = build_tool(
        "ocv_font", "exp",
        {"font": dot["glyphs"], "match": "exact", "expected": "2024",
         "dot_kernel": dot["dot_kernel"], "min_area": 6},
    )
    result = tool.inspect(image)
    assert result.passed and result.measured_value == "2024"


def test_train_then_read_loop(tmp_path):
    """Segment a sample → annotate → add to a font → the font reads new text."""
    sf, eng, _ = _setup(tmp_path)
    repo = FontRepository(sf)
    solid = next(f for f in builtin_fonts() if "Solid" in f["name"])

    fid = repo.create_font(eng, "Customer TTO", "tto", dot_kernel=0)
    # train from a sample image of the full character set we need
    sample = _compose(solid["glyphs"], "LOT420519")
    labelled = segment_sample(sample, "LOT420519")
    assert [c for c, _ in labelled] == list("LOT420519")  # suggested annotation
    total = repo.add_samples(eng, fid, labelled)
    assert total >= 9

    # the trained font now reads a different string made of those characters
    _, glyphs, kernel = repo.glyphs(fid)
    probe = _compose(solid["glyphs"], "LOT2495")
    text, score = read_text(probe, glyphs, n_chars=7, dot_kernel=kernel, min_area=6)
    assert text == "LOT2495"
    assert score > 0.8


def test_teach_ocv_font_tool(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.cli import build_code_demo_recipe
    from vis.engine.sim import SimulatedCodeCamera
    from vis.hmi.teach_window import TeachWindow

    sf, eng, _ = _setup(tmp_path)
    FontRepository(sf).ensure_builtins()
    frame = next(SimulatedCodeCamera("r", build_code_demo_recipe(), num_frames=1, defect_rate=0.0).frames())
    win = TeachWindow(user_id=eng, reference_image=frame.image, session_factory=sf, reject_lanes=["lane1"])
    win._recipe_name.setText("OCV demo")

    win._arm_tool("ocv_font")
    win._on_roi_drawn(20, 20, 120, 40)
    win._selected = ("tool", 0, 0)
    win._load_properties()
    tool = win._model.regions[0].tools[0]
    # a font auto-selected from the library and embedded into the config
    assert tool.config.get("font") and tool.config.get("font_name")
    embedded = tool.config["font_name"]

    # editing the match mode must NOT lose the trained font
    win._t_mode.setCurrentText("Contains text")
    assert win._model.regions[0].tools[0].config.get("font")
    assert win._model.regions[0].tools[0].config.get("font_name") == embedded
    assert win._model.regions[0].tools[0].config.get("match") == "contains"


def test_font_manager_train_flow(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from vis.hmi.font_window import FontManagerWindow, TrainFontDialog

    sf, eng, _ = _setup(tmp_path)
    repo = FontRepository(sf)
    repo.ensure_builtins()
    win = FontManagerWindow(sf, eng)
    assert win._table.rowCount() >= 3  # builtins listed

    # the annotation dialog: segment a sample, suggested labels editable
    solid = next(f for f in builtin_fonts() if "Solid" in f["name"])
    sample = _compose(solid["glyphs"], "EXP2026")
    dlg = TrainFontDialog(sample)
    dlg._text.setText("EXP2026")
    dlg._segment()
    assert len(dlg._edits) == 7
    dlg._edits[0][0].setText("E")  # operator confirms/corrects annotation
    dlg._accept_labels()
    assert [c for c, _ in dlg.labelled] == list("EXP2026")

    fid = repo.create_font(eng, "Trained via UI", "tto", 0)
    total = repo.add_samples(eng, fid, dlg.labelled)
    assert total == 7 * 5  # each annotated glyph + 4 augmented variants


def test_ocv_verify_mode_scores_against_expected(tmp_path):
    """True OCV: each position scored against the EXPECTED character — a wrong
    digit fails with a low per-char score; no irrelevant classification."""
    dot = next(f for f in builtin_fonts() if "5×7" in f["name"])
    image = _compose(dot["glyphs"], "2024")

    good = build_tool("ocv_font", "exp", {
        "font": dot["glyphs"], "match": "exact", "expected": "2024",
        "dot_kernel": dot["dot_kernel"]})
    result = good.inspect(image)
    assert result.passed and result.measured_value == "2024"
    assert len(result.detail["char_scores"]) == 4
    assert all(v >= 0.5 for v in result.detail["char_scores"])

    bad = build_tool("ocv_font", "exp", {
        "font": dot["glyphs"], "match": "exact", "expected": "2074",
        "dot_kernel": dot["dot_kernel"]})
    result = bad.inspect(image)
    assert not result.passed
    assert result.measured_value[2] == "?"          # the wrong position flagged
    # gated by the top-1 confusion margin (the printed '2' matches '2' better than
    # the expected '7'); the mismatch score stays well below a genuine match (~0.8+)
    assert result.detail["char_scores"][2] <= 0.6


def test_margin_gate_rejects_lookalike_of_another_char():
    """OCVMax-style confusion gate: a printed '8' must NOT verify as '0' even if
    its NCC vs '0' clears the accept threshold — '8' matches itself better
    (top-1 minus top-2 margin)."""
    from vis.tools.ocv_font import verify_text

    solid = next(f for f in builtin_fonts() if "Solid" in f["name"])
    image_8 = _compose(solid["glyphs"], "8")
    readback, _score, scores = verify_text(image_8, solid["glyphs"], "0",
                                           min_char_score=0.3, margin=0.05)
    assert readback == "?"  # rejected by the margin gate
    # and the genuine character still verifies
    readback, _score, _ = verify_text(image_8, solid["glyphs"], "8")
    assert readback == "8"


def test_charset_restriction_limits_candidates():
    from vis.tools.ocv_font import read_text

    solid = next(f for f in builtin_fonts() if "Solid" in f["name"])
    image = _compose(solid["glyphs"], "2026")
    text, _ = read_text(image, solid["glyphs"], n_chars=4, charset="digits")
    assert text == "2026"
    assert all(c.isdigit() for c in text)


def test_augmentation_multiplies_training_samples(tmp_path):
    from vis.tools.fontgen import augment_glyph

    sf, eng, _ = _setup(tmp_path)
    repo = FontRepository(sf)
    solid = next(f for f in builtin_fonts() if "Solid" in f["name"])
    template = solid["glyphs"]["A"][0]
    assert len(augment_glyph(template)) == 4  # ±3° rotation + dilate + erode

    fid = repo.create_font(eng, "Aug", "tto", 0)
    total = repo.add_samples(eng, fid, [("A", template)], augment=True)
    assert total == 5  # original + 4 variants
    total = repo.add_samples(eng, fid, [("B", template)], augment=False)
    assert total == 6


def test_print_quality_floors():
    import numpy as np

    from vis.engine.sim import _render_text
    from vis.tools.transform import print_quality

    good = _render_text("LOT42", 360, 90)  # tall, high contrast
    q = print_quality(good)
    assert q["warnings"] == []

    tiny = _render_text("LOT42", 70, 14)   # chars ~10px tall
    q = print_quality(tiny)
    assert any("20px" in w for w in q["warnings"])

    flat = np.full((60, 200, 3), 128, np.uint8)
    flat[20:40, 20:180] = 138               # ~10 grey levels of contrast
    q = print_quality(flat)
    assert any("grey levels" in w for w in q["warnings"])
