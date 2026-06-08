import csv

import pytest

pytest.importorskip("qrcode")

from PIL import Image  # noqa: E402

from vis.cli import build_code_demo_recipe  # noqa: E402
from vis.engine.sim import SimulatedCodeCamera  # noqa: E402
from vis.runtime.emulate import emulate_folder  # noqa: E402


def _write_images(directory, n, defect_rate):
    recipe = build_code_demo_recipe()
    frames = SimulatedCodeCamera("cam", recipe, num_frames=n, defect_rate=defect_rate, seed=1).frames()
    for i, frame in enumerate(frames):
        Image.fromarray(frame.image).save(directory / f"img_{i:03d}.png")


def test_emulate_folder_counts_and_writes_outputs(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    _write_images(images, 5, defect_rate=0.0)  # all good
    out = tmp_path / "out"

    recipe = build_code_demo_recipe()
    summary = emulate_folder(recipe, images, out)

    assert summary.total == 5
    assert summary.passed == 5 and summary.failed == 0
    # annotated images sorted into pass/
    assert len(list((out / "pass").glob("*.png"))) == 5
    # results.csv written with per-inspection rows
    with open(out / "results.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(r["product_passed"] == "True" for r in rows)
    assert all("read" in r for r in rows)


def test_emulate_folder_flags_failures(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    # write one image whose code won't match the recipe's expected value
    bad = next(SimulatedCodeCamera("c", build_code_demo_recipe(), num_frames=1, defect_rate=1.0).frames())
    Image.fromarray(bad.image).save(images / "bad.png")

    summary = emulate_folder(build_code_demo_recipe(), images, tmp_path / "out")
    assert summary.total == 1
    # a defective image should be flagged (sorted to fail/)
    assert summary.failed == 1
    assert (tmp_path / "out" / "fail" / "bad.png").exists()
