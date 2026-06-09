#!/usr/bin/env python3
"""Throughput benchmark — validates the 1000 images/min CPU target.

Measures how many frames/second the inspection pipeline sustains for code
verification (the fast path: zxing decode + GS1 parse + approximate grade), using
the in-process pool and the multiprocessing pool.

    python scripts/benchmark.py --frames 600 --workers 4

OCR/OCV text reading is slower per field (a few hundred ms with PP-OCR); for
text-heavy recipes use the recognition-only fast path or a licensed engine, and
scale workers. Codes are the throughput-critical case for serialization lines.
"""

from __future__ import annotations

import argparse
import time


def _run(pool, recipe, frames):
    from vis.engine.pipeline import InspectionPipeline
    from vis.engine.sim import SimulatedCodeCamera

    pipeline = InspectionPipeline(recipe, pool)
    n = 0
    for frame in SimulatedCodeCamera("cam1", recipe, num_frames=frames, defect_rate=0.1, seed=1).frames():
        pipeline.process_frame(frame)
        n += 1
    return n


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    from vis.cli import build_code_demo_recipe
    from vis.engine.pool import ProcessPool, SyncPool

    recipe = build_code_demo_recipe()
    regions = len(recipe.regions)
    print(f"Recipe: {regions} product region(s)/frame, code verification")

    for name, pool in (("in-process (SyncPool)", SyncPool()), (f"pool x{args.workers}", ProcessPool(args.workers))):
        t0 = time.perf_counter()
        n = _run(pool, recipe, args.frames)
        dt = time.perf_counter() - t0
        fps = n / dt if dt else 0
        close = getattr(pool, "close", None)
        if callable(close):
            close()
        print(f"  {name:22}: {n} frames in {dt:.2f}s = {fps:.0f} frames/s ({fps * 60:.0f}/min)")
    print("\nTarget: 1000 images/min (~17/s). Codes-only easily clears it on CPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
