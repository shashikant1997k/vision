"""OCR/OCV golden-set benchmark — the objective answer to "is our reading good?"

You don't judge a reader by clicking around: you keep a LABELLED set of real
field crops (the golden set) and score the engine on it after every change:

    vis-ocrbench --images golden/            # truth from filenames: LOT42__1.png
    vis-ocrbench --images golden/ --labels labels.csv
    vis-ocrbench --images golden/ --font "Line 3 CIJ 7x5"   # score the OCV font

Reports field accuracy (exact after tolerant folding), character accuracy
(Levenshtein), the confusion pairs to fix next, and read time. Keep one golden
set per customer print; a change is only an improvement if these numbers say so
(and it doubles as OQ evidence).
"""

from __future__ import annotations

import time
from pathlib import Path

from ..tools.ocr import _match_key


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_accuracy(truth: str, read: str) -> float:
    truth_key, read_key = _match_key(truth), _match_key(read)
    if not truth_key:
        return 1.0 if not read_key else 0.0
    return max(0.0, 1.0 - levenshtein(truth_key, read_key) / len(truth_key))


def _confusions(truth: str, read: str) -> list[tuple[str, str]]:
    """Positional char mismatches for equal-length keys (the common slip case)."""
    t, r = _match_key(truth), _match_key(read)
    if len(t) != len(r):
        return []
    return [(a, b) for a, b in zip(t, r) if a != b]


def evaluate(samples, read_fn) -> dict:
    """Score `read_fn(image) -> str` over [(name, image, truth), ...]."""
    rows = []
    confusions: dict[tuple[str, str], int] = {}
    t0 = time.perf_counter()
    for name, image, truth in samples:
        started = time.perf_counter()
        read = read_fn(image) or ""
        ms = (time.perf_counter() - started) * 1000
        exact = _match_key(read) == _match_key(truth)
        acc = char_accuracy(truth, read)
        for pair in _confusions(truth, read):
            confusions[pair] = confusions.get(pair, 0) + 1
        rows.append({"name": name, "truth": truth, "read": read,
                     "exact": exact, "char_acc": acc, "ms": ms})
    n = len(rows) or 1
    return {
        "samples": rows,
        "field_accuracy": sum(r["exact"] for r in rows) / n,
        "char_accuracy": sum(r["char_acc"] for r in rows) / n,
        "avg_ms": sum(r["ms"] for r in rows) / n,
        "total_s": time.perf_counter() - t0,
        "confusions": dict(sorted(confusions.items(), key=lambda kv: -kv[1])),
    }


def _load_samples(images_dir: str, labels_csv: str | None):
    import csv

    from ..camera.file_source import _IMAGE_EXTS, load_image

    directory = Path(images_dir)
    truths: dict[str, str] = {}
    if labels_csv:
        with open(labels_csv) as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    truths[row[0].strip()] = row[1].strip()
    samples = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if path.name in truths:
            truth = truths[path.name]
        else:  # filename convention: TRUTH__anything.png  (or the whole stem)
            truth = path.stem.split("__")[0]
        samples.append((path.name, load_image(path), truth))
    return samples


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Score OCR/OCV on a labelled golden set")
    parser.add_argument("--images", required=True, help="folder of field-crop images")
    parser.add_argument("--labels", help="CSV: filename,truth (else truth from filename before '__')")
    parser.add_argument("--font", help="score the trained OCV font with this name instead of OCR")
    parser.add_argument("--db", help="DATABASE_URL for --font (default: app data dir)")
    args = parser.parse_args()

    samples = _load_samples(args.images, args.labels)
    if not samples:
        print("No images found.")
        return 1

    if args.font:
        import os

        from ..db.base import make_engine, make_session_factory
        from ..db.fonts import FontRepository
        from ..tools.ocv_font import read_text

        url = args.db or os.environ.get("DATABASE_URL") or (
            f"sqlite:///{Path.home() / '.vision-inspection' / 'vis.db'}"
        )
        repo = FontRepository(make_session_factory(make_engine(url)))
        match = [f for f in repo.list_fonts() if f["name"] == args.font]
        if not match:
            print(f"Font {args.font!r} not found. Available: {[f['name'] for f in repo.list_fonts()]}")
            return 1
        _, glyphs, kernel = repo.glyphs(match[0]["id"])
        truth_by_image = {id(img): t for _n, img, t in samples}

        def read_fn(image):
            n = len(_match_key(truth_by_image.get(id(image), "")))
            return read_text(image, glyphs, n_chars=n or None, dot_kernel=kernel, min_area=6)[0]
    else:
        from ..tools.readers import get_text_reader

        reader = get_text_reader()

        def read_fn(image):
            return reader(image, {})[0]

    report = evaluate(samples, read_fn)
    print(f"\nGolden set: {len(samples)} samples ({args.images})")
    print(f"  Field accuracy : {report['field_accuracy'] * 100:.1f} %  (exact after tolerant folding)")
    print(f"  Char accuracy  : {report['char_accuracy'] * 100:.1f} %")
    print(f"  Avg read time  : {report['avg_ms']:.0f} ms")
    if report["confusions"]:
        print("  Top confusions :", ", ".join(f"{a}->{b} x{n}" for (a, b), n in list(report["confusions"].items())[:8]))
    failed = [r for r in report["samples"] if not r["exact"]]
    if failed:
        print(f"\n  {len(failed)} misread(s):")
        for r in failed[:20]:
            print(f"    {r['name']:30} truth {r['truth']!r:20} read {r['read']!r}")
    else:
        print("  All samples read correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
