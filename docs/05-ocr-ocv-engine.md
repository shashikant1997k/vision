# 05 — OCR/OCV Inspection Engine

The throughput-critical subsystem. OCR/OCV is the expensive part, so it is designed as a first-class, budgeted pipeline.

## Implemented (current)

`src/vis/tools/ocr.py` — `OcrTextTool` (type `ocv_text`) uses **RapidOCR (PP-OCR on ONNX
Runtime)**, the cross-platform "ONNX PaddleOCR" path (runs on macOS, CPU). Engine loaded once
per process (warm). Supports exact / contains / regex matching (regex validates date/format),
case + whitespace normalisation, and a confidence floor. Currently runs the **full det+rec
pipeline** for robustness; the **recognition-only + INT8 mobile** fast path below is the
production throughput optimisation (not yet wired). Optional dep: `pip install '.[ocr]'`.

## Targets & constraints

- **Throughput:** baseline reference 1000 images/min ≈ ~17 frames/sec. **But with multi-camera + multi-product-in-FOV (Phase 1), size on total ops:** `ops/min = frames/min × cameras × regions-per-frame × ROIs-per-region`. A single frame can now yield many OCV ops, so the worker pool must be sized on ops, not frames. **This is a CPU-only sizing risk — must be measured on a real spike** (see backlog).
- **Hardware baseline:** **CPU-only** (most install sites have no GPU). GPU is an optional accelerator only, **never required**. If multi-product op-counts exceed CPU headroom, GPU becomes the escape hatch for heavy stations.
- **Mode:** mostly **OCV (verification)** — the expected text comes from the batch record, so we verify "does it match?" rather than blind-read "what does it say?"
- **Pooling:** one shared worker pool serves all cameras and regions (better core utilization than per-camera pools).

### Capacity envelope (confirmed config, 2026-06-07)

| Parameter | Typical | Max (configurable) |
|---|---|---|
| Cameras per line PC (C) | 2–3 | 4 |
| Products per FOV (P) | 2–3 | 4 |
| Text fields / product | 4–7 | 7 |
| Codes / product (DataMatrix / QR / 1D / 2D) | 1 | 1 |
| **ROIs / product (R)** | ~5–6 | ~8 |

`ops/sec = C × (frames/sec per camera) × P × R`. ROIs per camera shot = P×R (≈18 typical, **32 worst case**).

Rough sizing at ~15 ms/ROI/core (OCV; grading is heavier):
- **Typical** (3 cams, 3 prod, ~6 ROI, ~4 fps/cam) ≈ **~220 ops/s** → ~3–4 cores → comfortable on an 8-core PC.
- **Worst case** (4 cams, 4 prod, 8 ROI, ~4 fps/cam) ≈ **~530 ops/s** → ~8 cores → needs a strong 12–16 core CPU; still CPU-only feasible with ~10–12 workers.

**Verdict:** typical config is comfortably CPU-only; worst-case-maxed is the threshold where a stronger CPU or optional GPU is warranted. **Binding unknown = line speed (frames/s per camera) — still to confirm.** **Wildcard = ISO 15415/15416 grading cost** (may bottleneck before OCR; pending research).

## Engine choice (lightest / fastest for this case)

> **PaddleOCR PP-OCR _mobile_ recognition model → exported to ONNX → INT8-quantized → served from a pool of warm ONNX Runtime worker processes, recognition-only on the cropped ROI, compared against the expected string.**

| Choice | Why it's the light/fast option |
|---|---|
| PP-OCR **mobile** (not server) | A few MB, built for edge CPU |
| **Recognition-only** (skip detection) | ROI is known from the recipe — no need to *find* text; ~2–3× faster |
| **ONNX + INT8** | ONNX Runtime CPU beats native Paddle; INT8 ~halves latency, negligible accuracy loss on clean codes |
| **OCV compare** with constrained charset | Smaller dictionary = faster decode + fewer false reads |
| **Warm worker pool** | Model loaded once per worker at startup; per-image cost is pure inference |

**Expected:** PP-OCR mobile rec, INT8, modern multi-core CPU ≈ 5–25 ms/ROI/core. **3–4 worker processes clear 1000/min with headroom** — system is likely trigger/IO-bound, not OCR-bound.

## Pipeline

```
[Acquire proc]  GigE/GenICam grab → frame into shared-memory ring buffer
      │  (pass frame handle + recipe ROIs over the queue — NOT the pixels)
      ▼
[Dispatcher]    crop each ROI → small ROI image → task queue
      │
      ▼
[Worker pool]   N processes, each holds a warm ONNX Runtime session
      │         recognition → text + confidence;  code workers → decode + ISO grade
      ▼
[Aggregator]    collect ROI results per product → pass/fail logic →
                reject I/O + audit log + image archive
```

## Engineering rules (make-or-break)

- **Multiprocessing, not threading** for the CPU-bound work. (ONNX Runtime releases the GIL during native inference, but surrounding Python pre/post-processing does not.)
- **Shared memory for frames** (`multiprocessing.shared_memory` ring buffer). **Never pickle full frames across queues** — crop early so workers touch only small ROIs.
- **Warm, persistent sessions** — never load the model per image.
- **Threading knob:** `intra_op_num_threads = 1` inside each worker; scale by **process count ≈ cores − 2**. Letting every worker grab all cores causes oversubscription and *slower* throughput.
- **Bounded queues + deterministic backpressure** — if OCR falls behind, drop or block *deterministically* and **log every dropped frame** (a silently skipped product is a compliance event), never skip silently.

## Future refinement (not day one)

Add a **classic template/correlation OCV fast-path** (OCRMax-style, no neural net — deterministic, easiest to validate) for clean fixed-font codes; keep ONNX-PaddleOCR as the **robust-path** for dot-matrix / CIJ / degraded prints. Both implement the same **inspection-tool interface**, so this is an addition, not a re-architecture.

## Pharma validation of a neural OCR

PaddleOCR is a deep-learning model, so it must be **locked**:

- Pin **one ONNX model version**; record its `sha256` in the **ModelVersion** registry.
- **Log the model version with every result** (`ToolResult.model_version_id`).
- Any model swap = a **change-control / revalidation event**.

This is the "locked model under formal change control" pattern that regulators require (FDA PCCP, GAMP 5 2nd ed) — it's what makes shipping a neural OCR in a regulated product defensible.

**Framing:** the **base engine** = locked ONNX-PaddleOCR (OCV-first). The **optional licensed "AI module"** = trainable/adaptive tools (anomaly detection, customer-retrained dictionaries) — *not* this base OCR. Don't promise a customer "no AI / no GPU" and then ship a neural OCR without this distinction.
