# Vision Inspection — application guide

A machine-vision inspection system for pharmaceutical packaging lines: it reads
and verifies printed coding (batch, MFG, EXP, MRP), barcodes and 2D codes,
grades print quality, rejects bad product through the line's I/O, and keeps a
21 CFR Part 11 audit trail of everything it did.

Built by Control Print to replace bought-in vision software with a product we
own, license and can extend to new applications (label inspection, fill level,
sorting) without rewriting the engine.

---

## 1. Getting it running

```bash
git clone git@github.com:shashikant1997k/vision.git
cd vision
python3 -m venv .venv
.venv/bin/pip install -e ".[engine,ocr,dev]"

# the full app, no camera needed — replays real product images
VIS_CAMERA=file VIS_TEXT_READER=vis_ocr .venv/bin/vis-hmi
```

First login is `admin` / `admin123` (change it immediately — it is seeded only
so a fresh install can be opened).

**Models.** OCR needs `ocrab_svtr256.onnx` + `textline_det.onnx` from the
[ocr-trainer](https://github.com/shashikant1997k/ocr-trainer) repo's `model/`
folder. The reader looks in `~/.vision-inspection/`, `~/Personal/camera/ocr-trainer/model`,
`~/camera/ocr-trainer/model`, `./model`, or wherever `VIS_OCR_MODEL` points.

Camera setup — including why macOS cannot run one — is in
[docs/22-camera-setup.md](docs/22-camera-setup.md).

---

## 2. How the app is put together

```
camera ──► pipeline ──► tools ──► aggregator ──► reject I/O
              │           │            │
           recipe      readers      audit trail / archive / reports
```

| Layer | Where | What it does |
|---|---|---|
| Camera | `src/vis/camera/` | file replay, Aravis, GenTL, Hikrobot, simulator — one interface |
| Recipe | `src/vis/domain/` | products → regions → tools + ROIs; what to inspect |
| Pipeline | `src/vis/engine/` | crop regions/ROIs, run tools in a thread pool, aggregate |
| Tools | `src/vis/tools/` | the inspections themselves (below) |
| Readers | `src/vis/tools/readers.py` | pluggable OCR/code engines behind one seam |
| Runtime | `src/vis/runtime/` | the run loop, live stats, reject handling, image archive |
| I/O | `src/vis/io/` | digital outputs, encoder-tracked ejection, Modbus TCP |
| Data | `src/vis/db/` | SQLAlchemy models, batches, users, audit trail |
| HMI | `src/vis/hmi/` | the PySide6 operator interface |
| Licensing | `src/vis/licensing/` | signed licenses, capability packs, model encryption |

### Inspection tools

| Tool | Purpose |
|---|---|
| `ocv_text` | read/verify a text field (the main pharma coding tool) |
| `ocv_font` | per-character template OCV |
| `code_verify` | 1D barcodes, DataMatrix, QR, GS1 parsing, quality grading |
| `pharmacode` | Laetus one-track code — pharma line clearance (reader, not a tool type) |
| `print_inspect` | grade print QUALITY (fading, smear, dropout) even when text is right |
| `template_match` | golden-artwork compare, with optional rotation tolerance |
| `presence` / `measure` / `color_check` | classic checks |

A region can carry a **fixture** (a taught anchor patch). The pipeline locates it
each frame and shifts every ROI by the offset found, so inspection follows the
part instead of assuming it lands in exactly the same place.

---

## 3. Reading text — the part that matters

Two models, in sequence:

1. **`textline_det.onnx`** (YOLO11-nano) finds the text lines in the frame.
2. **`ocrab_svtr256.onnx`** (SVTR — CNN + Transformer + CTC) reads one line crop.

Measured on the 96-crop real blister golden set:

| Decoding | Field accuracy | Char accuracy | ms/field |
|---|---|---|---|
| greedy (raw model) | 38.5% | 90.3% | 0.1 |
| **grammar-constrained** | **97.9%** | 98.1% | 3.8 |

**Always state the decoding mode when quoting accuracy.** The raw recogniser is
not production-grade on this print; the constrained decoder is what makes it so.

### Why constrained decoding wins

A field fails if *any* character fails, so 90% character accuracy over a 10-character
field is only 0.9¹⁰ ≈ 35%. But industrial fields have grammar — `EXP. 10/2026` is
`EXP\. \d{2}/\d{4}`. `src/vis/tools/constrained_decode.py` runs CTC beam search
where each beam carries the state of a small regex automaton, so a
grammar-illegal character is never even considered and the correct one wins.

Set it per tool: `match: "regex"` + `pattern`, or `match: "exact"` + `expected`.

> **Safety:** a constrained decode always returns a grammar-legal string — it
> would "read" the expected text off a blank crop. The **confidence must be
> thresholded**; measured separation is ~0.995 (right) vs ~0.001 (wrong/blank).

### Configuring another font or print process

One model per print technology — never one model for all fonts. Merging them
enlarges the class space, adds cross-font confusions, slows inference, and means
every retrain puts already-validated fonts back into revalidation.

1. Train a model in `ocr-trainer` (see its `START_HERE.md`).
2. Ship `<name>.onnx` + `<name>.charset.txt` (+ `.meta.json` with `img_w`).
3. Point a recipe's tool at it via `VIS_OCR_MODEL` / the reader seam.

---

## 4. Running production

**Batch → inspect → close.** A batch is the unit of record: results, images and
audit entries hang off it, and closing it is an electronic-signature event.

- **Live screen** shows the feed with overlays, per-camera pass/fail, the scanned
  values, and the **last reject with the reason it failed** (which inspection,
  what it read, what was expected).
- **Context bar** keeps batch / product / user / role visible on every screen.
- **Reports** — batch records, rejects, events, audit trail — one screen, tabs.
- **Line stop**: N consecutive rejects stops a production batch and alarms
  (`line.alarm_consecutive_rejects`), because that means a systematic failure.
- **Challenge test**: `line.require_challenge_hours` refuses to start a batch
  unless a known-bad sample was correctly rejected within N hours.

### Image archive

Configurable in the site config or by env (`VIS_IMAGE_POLICY`, `VIS_IMAGE_DIR`):

```json
"images": {"policy": "fails", "dir": "", "separate_folders": true, "write_analysis": true}
```

`policy` is `none` | `fails` | `all`. Images land in `<root>/batch_N/pass` and
`/reject`, and **every reject gets a JSON sidecar** naming the failed inspection,
what it read, what was expected, the confidence and the model version — so
"why was this rejected?" is answerable from the folder alone, months later.

### Line I/O

`src/vis/io/` drives ejectors, beacons and the buzzer. Rejects are tracked by
**encoder distance**, not a timer, so ejection is correct at any line speed.

The rule: **the PC decides, deterministic hardware actuates.** Never put the
reject pulse on a Python round-trip. Modbus TCP writes are verified, retried once
after a reconnect, and raise `IOFault` if they still fail — a vision system that
silently stops rejecting is more dangerous than one that stops running.

---

## 5. Licensing and packaging

One binary; features unlock from the content of a signed license
(`src/vis/licensing/`), the same model HALCON/MERLIC/Aurora use.

- **Ed25519-signed license files**, verified fully offline (pharma lines are
  air-gapped). Editing one byte invalidates the signature.
- **Capability packs** are the unit of sale — `pharma-ocv`, `codes`,
  `cij-dotmatrix`, `label-qc`, `fill-level`, `sorting`. Unlicensed packs stay
  *visible but locked* in the teach screen as an upsell surface.
- **Node-locking** to a station fingerprint; **expiry with a grace window** for AMC.
- **Per-customer encrypted models** (AES-GCM, key derived from the license):
  a copied model file is inert elsewhere and names the license it leaked from.

Vendor side (never on a customer machine):

```bash
vis-license keygen                       # once — keep the private key offline
vis-license fingerprint                  # on the customer PC
vis-license issue --customer "Plant X" --packs pharma-ocv,codes --machine <fp>
vis-license package --license CPL-2026-0001 --models model/*.onnx --out dist/
```

Set `VIS_LICENSE_REQUIRED=1` and `VIS_MODEL_STRICT=1` on a line PC: no valid
license or an unmanifested/tampered model then refuses to start.

---

## 6. Compliance (21 CFR Part 11)

- Users, roles and permissions; forced password policy; audit-trail review with
  electronic signature.
- Every inspection records the **model version** that made the decision.
- Models carry a **SHA-256 manifest**; a swapped or corrupted model is refused.
- Recipes are versioned and approval-gated; batch release is signed.
- Validation material lives in `docs/validation/` (plan, IQ, OQ, Part 11 matrix,
  traceability). `docs/06-compliance.md` maps requirements to implementation.

---

## 7. Development

```bash
.venv/bin/python -m pytest tests -q          # 516 tests
.venv/bin/ruff check src tests
.venv/bin/python scripts/bench_constrained_decode.py    # OCR accuracy benchmark
```

Useful environment variables:

| Variable | Effect |
|---|---|
| `VIS_CAMERA` | `file` / `aravis` / `gige` / `hikrobot` |
| `VIS_FILE_DIR` | image folder for `VIS_CAMERA=file` |
| `VIS_TEXT_READER` | `vis_ocr` (trained model) or `builtin` |
| `VIS_OCR_MODEL` | explicit model path |
| `VIS_LICENSE` / `VIS_LICENSE_REQUIRED` | license file / refuse to run unlicensed |
| `VIS_MODEL_STRICT` | require model manifests + OCV calibration |
| `VIS_IMAGE_POLICY` / `VIS_IMAGE_DIR` | image archive |
| `VIS_OCR_DETECTOR_FALLBACK` | `0` disables the slow detector rescue |
| `DATABASE_URL` | defaults to SQLite in the data dir |

Deeper design docs are in `docs/` — architecture (04), OCR/OCV engine (05),
compliance (06), camera module (10), integration protocol (12), web API (18),
camera setup (22), and `docs/decisions/decision-log.md` for why things are the
way they are.

---

## 8. Known limits — read before promising anything

- **macOS cannot run a live camera.** Proven across three driver stacks. Develop
  with `VIS_CAMERA=file`; capture on Windows or Linux.
- **Raw OCR is 38.5% field accuracy**; 97.9% comes from constrained decoding.
  Never quote the headline without the decoding mode.
- **`template_match` cannot verify text.** Under realistic print variation, good
  and wrong text scores overlap — no threshold separates them. Use OCV.
  `suggest_min_score()` will tell you when a threshold is untrustworthy.
- **`print_inspect` needs a taught reference** to catch uniform fade; without one
  it only sees variation *within* a line.
- **Before a first sale:** compiled build (Nuitka), a production signing keypair,
  and the executed IQ/OQ document pack. None of these exist yet.
