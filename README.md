# Vision Inspection System (working title)

An **inline print & code verification system** for pharmaceutical production lines. It integrates with **GigE Vision** cameras to verify printing and coding on products, cartons, labels, blisters, vials and ampoules — lot/batch, expiry, MRP text, and GS1 DataMatrix / serialization codes — and rejects non-conforming product in real time.

Built **compliance-first** (21 CFR Part 11 / EU GMP Annex 11), on an **open Python stack**, with **AI as an optional, validated module** rather than a mandatory black box.

> **Positioning in one line:** an open (Python/GigE), compliance-first inline print & code verifier, with explainable AI as an optional validated module, built so plant QA can run change-control themselves.

## Why this exists (the market gap)

The market splits into two camps and neither serves regulated print-inspection well:

- **General machine-vision platforms** (Cognex, Keyence, Hikrobot, Zebra Aurora, MVTec HALCON) — strong vision/AI tech, but **not turnkey-validated for pharma**; Part 11, IQ/OQ and serialization are left to the integrator.
- **Pharma specialists** (SEA Vision, Lake Image) — bundle GMP compliance and validation docs, but **older/closed tech, less modern AI, expensive**.

This product targets the **missing middle**: modern, explainable AI tooling **with built-in, validation-ready pharma compliance**.

## Status

**Working application.** The full single-station system is implemented and tested
(140+ automated tests, lint-clean): camera acquisition, a direct-manipulation
teach screen, a live multi-camera run with pass/fail + reject I/O, batch
management with electronic signatures and reports, and an append-only audit
trail. The OCR/OCV *reading* sits behind a provider seam so a licensed engine can
be dropped in. See [`docs/`](docs/) for the design record.

## What's built

**Operator HMI (`vis-hmi`)**
- **Login / RBAC** — roles (admin, engineer, qa_manager, operator); PBKDF2 hashing.
- **Teach screen** — acquire from the line or **load your own product images**;
  **zoom/pan** + **drag-handle ROIs**; inspection palette (Read Code, Read Text,
  Presence/Absence, Measure, Colour, Match-template); **part location** (ROIs follow
  the part); **per-ROI rotation**; match modes incl. **batch-fed values**; per-tool
  editors; Test (per-inspection ✓/✗ + read value); Save → **Approve (e-signature)**.
- **Live run** — **multi-camera tabs**, each with its **own recipe**; annotated feed,
  counters, **yield % + reject-reason breakdown**, run/idle state; **reject review**
  filmstrip; batch start/close (e-signature) → signed HTML report.
- **Offline emulation** — run a recipe over a folder of images (pass/fail sort + CSV).
- **Stations admin** — define stations → cameras → assigned recipes (persisted, audited).
- **Camera settings** — exposure/gain, trigger (hw/sw/encoder), **lighting/strobe**,
  sensor AOI, gamma, **pixel↔mm calibration**, focus assist, live preview.
- **Recipe import/export**, **DB backup/restore**, **FTP/network image archiving**.

**Integration** — digital I/O, **Modbus**, **EtherNet/IP** PLC link, **TCP/JSON**
result publishing, and **encoder/pulse-based reject** (speed-independent ejection).

**Compliance** — append-only **hash-chained audit trail**, two-component
**electronic signatures**, recipe versioning + approval, ALCOA+ data model.

**CLI tools**
```bash
vis-hmi                                   # the operator application
vis-emulate --images DIR --out DIR        # run a recipe over saved images
vis-backup backup|restore FILE            # database snapshot / restore
vis-demo --frames 10 --defect-rate 0.3    # headless pipeline demo (no hardware)
python scripts/fetch_ocr_models.py        # download PP-OCRv4 OCR models
```

> **OCR/OCV reading:** industrial coding is often dot-matrix (CIJ/TIJ); the system
> ships a **font-trained OCV** engine and a PP-OCR fallback, but for production a
> **licensed OCR/OCV library** drops into the reader seam
> (`vis.tools.readers.register_text_reader`). Reading accuracy depends on proper
> on-line imaging (square-on, controlled lighting) — not a phone photo.

## Documentation map

| Doc | Purpose |
|---|---|
| [Vision, Scope & Positioning](docs/01-vision-scope-positioning.md) | What we're building, for whom, and why we win |
| [Competitive Research](docs/02-competitive-research.md) | Verified findings on incumbents + exploitable weaknesses |
| [Requirements & Roadmap](docs/03-requirements-and-roadmap.md) | Feature catalog, Phase 1 MVP vs. later phases |
| [System Architecture](docs/04-system-architecture.md) | The 5 layers, components, data model, tech stack |
| [OCR/OCV Engine Design](docs/05-ocr-ocv-engine.md) | The throughput-critical inspection engine |
| [Compliance (21 CFR Part 11 / Annex 11)](docs/06-compliance.md) | Regulatory requirements and how we meet them |
| [Camera Module](docs/10-camera-module.md) | Vendor-neutral camera hardware layer |
| [Decision Log](docs/decisions/decision-log.md) | Key decisions and their rationale |
| [Open Questions & Research Backlog](docs/07-research-backlog.md) | What we still need to confirm |
| [Validation Package (IQ/OQ, Part 11)](docs/validation/README.md) | Pharma deployment qualification |
| [Deployment & Installation](docs/deployment/installation.md) | Install, configure, run; packaging |

## Key facts

- **Target industry (first):** Pharmaceutical (regulated).
- **Camera standard:** GigE Vision / GenICam (vendor-neutral).
- **Stack:** Python — PySide6 HMI + FastAPI backend + ONNX/PaddleOCR engine.
- **Throughput target:** 1000 images/min (~17 reads/sec), **CPU-only baseline**.
- **AI:** optional, licensed, validated module (not required for the base product).
- **Serialization/aggregation:** Phase 2 — but the data model is serialization-ready from day one.

## Getting started

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,hmi,codes,ocr,engine,io]"

.venv/bin/python -m pytest -q          # run the tests (offscreen Qt)
.venv/bin/vis-hmi                      # launch the operator application
```

First launch seeds a default admin (`admin` / `admin123`) and a SQLite database at
`~/.vision-inspection/vis.db`. The app runs against a **simulated camera** on
macOS/Windows (no hardware needed); on a Linux/Windows line PC with GigE cameras,
install the `camera` extra (Harvester/GenTL) for real acquisition.

**Try it end to end (simulated):**
1. `vis-hmi` → log in (`admin` / `admin123`).
2. **Teach on images…** → load a few sample product images → draw boxes → set values → **Test** → **Save** → **Approve**.
3. On the live screen pick the recipe → enter a batch no. → **Start** → **Stop** → **Close batch** (signs + writes an HTML report).

### Camera bring-up note
Reading is only as good as the image. Use a **square-on, well-lit** capture from the
production camera (dome/bar/coaxial lighting, ≥ ~20 px character height). Set the
whole-image rotation or per-ROI rotation so print is upright. See
[docs/10-camera-module.md](docs/10-camera-module.md).
