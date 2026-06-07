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

Early kickoff — requirements and architecture defined; implementation not yet started. See [`docs/`](docs/) for the full project record.

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

## Getting started (development)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"

# run the tests
.venv/bin/python -m pytest -q

# run the walking-skeleton demo (fake camera, no hardware needed)
.venv/bin/python -m vis.cli --frames 10 --defect-rate 0.3            # in-process
.venv/bin/python -m vis.cli --frames 10 --defect-rate 0.3 --workers 4  # multiprocessing pool
```

The walking skeleton runs the full pipeline — fake camera → multi-product regions →
crop → worker pool → per-region pass/fail → per-lane reject routing — with no camera
hardware, so it runs on macOS or Windows. See [docs/08-project-structure.md](docs/08-project-structure.md).
