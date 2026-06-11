"""Golden-set OCR benchmark harness."""

import pytest

pytest.importorskip("rapidocr_onnxruntime")

from PIL import Image  # noqa: E402

from vis.engine.sim import _render_text  # noqa: E402
from vis.runtime.ocr_bench import _load_samples, char_accuracy, evaluate, levenshtein  # noqa: E402


def test_levenshtein_and_char_accuracy():
    assert levenshtein("LOT42", "LOT42") == 0
    assert levenshtein("LOT42", "LOT4") == 1
    assert char_accuracy("LOT42", "LOT42") == 1.0
    assert char_accuracy("B.No.TEST12345", "B.N0.TEST12345") == 1.0  # folded
    assert char_accuracy("MFG.10/2025", "MFG.10/2026") < 1.0


def test_golden_set_scores_clean_renders(tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    for truth in ("LOT42", "EXP1026", "MRP00000"):
        Image.fromarray(_render_text(truth, 360, 90)).save(golden / f"{truth}__1.png")

    samples = _load_samples(str(golden), None)
    assert [s[2] for s in samples] == ["EXP1026", "LOT42", "MRP00000"]  # truth from names

    from vis.tools.readers import get_text_reader

    reader = get_text_reader()
    report = evaluate(samples, lambda img: reader(img, {})[0])
    assert report["field_accuracy"] == 1.0       # clean renders read perfectly
    assert report["char_accuracy"] == 1.0
    assert report["avg_ms"] > 0
    assert report["confusions"] == {}


def test_evaluate_flags_misreads():
    report = evaluate(
        [("a", None, "LOT42"), ("b", None, "EXP10")],
        lambda img: "LOT42",  # always reads LOT42
    )
    assert report["field_accuracy"] == 0.5
    assert 0 < report["char_accuracy"] < 1.0
