"""Offline emulation / playback.

Run a recipe over a folder of saved images — no camera needed. Produces a
pass/fail record per image, sorts annotated images into pass/ and fail/ folders,
and writes a results CSV. Used for GMP validation/regression (replay a known set
of good/bad images and confirm the recipe still grades them correctly) and for
tuning a recipe on real captured product images.

Mirrors the offline-playback feature of Cognex In-Sight EasyBuilder.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..camera.file_source import _IMAGE_EXTS, load_image
from ..engine.frame import Frame
from ..engine.pipeline import InspectionPipeline
from ..engine.pool import SyncPool
from .overlay import draw_overlay


@dataclass
class EmulationSummary:
    total: int
    passed: int
    failed: int
    records: list  # list of (image_name, passed, region_results)


def _disp(value) -> str:
    return "" if value is None else str(value).replace("\x1d", "<GS>")


def emulate_folder(recipe, image_dir, out_dir=None, pool=None) -> EmulationSummary:
    """Run `recipe` over every image in `image_dir`. If `out_dir` is given, write
    annotated images into pass/ and fail/ subfolders plus results.csv."""
    pool = pool or SyncPool()
    pipeline = InspectionPipeline(recipe, pool)
    image_dir = Path(image_dir)
    paths = sorted(p for p in image_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)

    out = Path(out_dir) if out_dir else None
    if out is not None:
        (out / "pass").mkdir(parents=True, exist_ok=True)
        (out / "fail").mkdir(parents=True, exist_ok=True)
        csv_rows = []

    records = []
    n_pass = 0
    for i, path in enumerate(paths):
        image = load_image(path)
        results = pipeline.process_frame(Frame(path.name, i, image, 0.0))
        passed = bool(results) and all(r.passed for r in results)
        n_pass += int(passed)
        records.append((path.name, passed, results))

        if out is not None:
            from PIL import Image

            annotated = draw_overlay(image, recipe, results)
            Image.fromarray(annotated).save(out / ("pass" if passed else "fail") / path.name)
            for r in results:
                for tr in r.tool_results:
                    csv_rows.append(
                        {
                            "image": path.name,
                            "product": r.region_id,
                            "product_passed": r.passed,
                            "inspection": tr.tool_id,
                            "inspection_passed": tr.passed,
                            "read": _disp(tr.measured_value),
                            "expected": _disp(tr.expected_value),
                        }
                    )

    if out is not None:
        with open(out / "results.csv", "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["image", "product", "product_passed", "inspection",
                            "inspection_passed", "read", "expected"],
            )
            writer.writeheader()
            writer.writerows(csv_rows)

    return EmulationSummary(total=len(records), passed=n_pass, failed=len(records) - n_pass, records=records)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Offline emulation: run a recipe over a folder of images")
    parser.add_argument("--images", required=True, help="folder of product images to inspect")
    parser.add_argument("--out", help="folder to write annotated pass/fail images + results.csv")
    parser.add_argument("--recipe-id", type=int, help="approved recipe id from the DB (default: built-in demo)")
    parser.add_argument("--db", help="DATABASE_URL (default: app data dir)")
    args = parser.parse_args()

    if args.recipe_id is not None:
        import os

        from ..db.base import make_engine, make_session_factory
        from ..db.store import RecipeRepository

        url = args.db or os.environ.get("DATABASE_URL")
        if not url:
            url = f"sqlite:///{Path.home() / '.vision-inspection' / 'vis.db'}"
        sf = make_session_factory(make_engine(url))
        recipe = RecipeRepository(sf).load(args.recipe_id)
    else:
        from ..cli import build_code_demo_recipe

        recipe = build_code_demo_recipe()

    summary = emulate_folder(recipe, args.images, args.out)
    print(f"Emulated {summary.total} images: {summary.passed} pass, {summary.failed} fail")
    if args.out:
        print(f"Annotated images + results.csv written to {args.out}")
    for name, passed, _ in summary.records:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
