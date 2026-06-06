# Decision Log

Lightweight ADR-style record of decisions and their rationale. Newest at top. Status: Accepted unless noted.

---

## D-014 — External integration: TCP/IP result publishing to third-party apps
**Date:** 2026-06-07 · **Status:** Accepted
**Decision:** A configurable integration layer publishes scanned/inspection data to **any third-party application over TCP/IP**. Each connector is configurable as **TCP server** (peer connects to us) or **TCP client** (we connect to their host:port), with a configurable **message format** (line-framed JSON default + delimited/templated for host systems), pushing **per inspection result in real time**. **Store-and-forward buffering + auto-reconnect** so data survives peer downtime. Subscribes to the internal **EventBus** (decoupled from the engine). All egress logged for audit; connector config under change control.
**Why:** User requirement — connect the app with any third-party app and pass scanned data. The EventBus was designed for exactly this.
**Scope:** Phase 1 = generic TCP/IP push. Richer industrial protocols (OPC-UA, Profinet, EtherNet/IP) and MES/ERP remain later phases.

## D-013 — Database: PostgreSQL (+ JSONB), via SQLAlchemy
**Date:** 2026-06-07 · **Status:** Accepted
**Decision:** PostgreSQL is the standard DB (line PC and future central/fleet). Use **JSONB** for variable fields (tool config, ISO-grade parameters) inside a relational schema. Access via **SQLAlchemy + Alembic** migrations. **Images on the filesystem** (path + checksum in DB), never blobs in DB. **Audit tables append-only enforced at the DB** (REVOKE UPDATE/DELETE from the app role). Partition high-volume result tables by time. SQLite for tests only.
**Why:** Concurrent writers (engine + backend + HMI); ACID across a relationship-heavy model; DB-level append-only for Part 11; SQL reporting; JSONB covers document flexibility; scales to fleet; free + cross-platform (Mac/Windows dev parity).
**MongoDB considered & declined:** flexible schema is a GxP/validation *liability*; relational integrity, cross-document ACID, and SQL reporting matter more; Postgres JSONB covers Mongo's one real edge. SQLAlchemy keeps a customer-mandated **SQL Server** swap a config change, not a rewrite.

## D-012 — Code grading: inline "process-control grade" + certified verifier for sampling
**Date:** 2026-06-07 · **Status:** Accepted (confirmed by user 2026-06-07)
**Finding (verified):** A *certified* ISO 15415/15416 grade requires conformant verifier hardware per ISO/IEC 15426-1/-2 (calibration, certified test cards, matched aperture). Software/inline camera cannot produce a certified grade — only an approximate one. OSS Python libs decode only.
**Decision:** Inline = decode + **content verification** + **approximate ISO-style quality metrics** labeled "process-control grade, NOT certified." Certified grading handled via a **sampling workflow** with a real verifier (Omron LVS / Axicon / Cognex), results recorded/imported; optional verifier-SDK integration later.
**Why:** Honest, defensible, matches industry practice; avoids non-compliant claims. See [compliance](../06-compliance.md).

## D-011 — Acquisition layer: Harvester + GenTL, vendor SDK as fallback
**Date:** 2026-06-07 · **Status:** Accepted
**Decision:** Vendor-neutral GigE Vision acquisition via **genicam Harvester** + vendor `.cti` GenTL producers on Windows. Thin acquisition abstraction so we can drop to a vendor SDK (pypylon / VmbPy / Hikrobot MVS) for camera-specific features. One acquisition process per camera.
**Why (verified):** Harvester is neutral at the GenTL/GenICam layer; vendor SDKs are mature fallbacks; Hikrobot GigE supports A/B encoder triggering for line tracking.
**Notes:** macOS GigE support is poor → dev on Mac uses the fake camera; real-camera work on Windows. NIC tuning: jumbo 9014, RX buffers 2048, tune interrupt moderation toward latency (reject timing). Needs a multi-vendor-producer interop spike + a sustain/latency benchmark.

## D-010 — Multi-camera + multi-product-in-one-FOV are in Phase 1 (MVP)
**Date:** 2026-06-07 · **Status:** Accepted
**Decision:** Moved from Phase 2 into the MVP. The line PC drives **multiple cameras**, and a single camera frame may contain **multiple products**, each in its own **Region/track** with its own ROIs, pass/fail, and **reject lane**.
**Why:** User confirmed real lines need it from day one.
**Consequence:** Recipe is no longer a flat tool list — it's `Recipe → Regions → Tools`. New entities: Station, Camera, RejectOutput, Region, CameraAssignment, FrameCapture; InspectionResult is now per-Region. One acquisition process per camera; one shared OCR worker pool. Throughput must be sized on **ops** (frames × cameras × regions × ROIs), not frames — a CPU-only sizing risk to validate via spike. See [architecture](../04-system-architecture.md) and [engine](../05-ocr-ocv-engine.md).

## D-009 — Documentation-first kickoff; research continues in parallel
**Date:** 2026-06-06 · **Status:** Accepted
Establish the project doc set (this `docs/` tree) as the foundation; treat open questions as a living [research backlog](../07-research-backlog.md) chipped away in parallel rather than blocking the kickoff.

## D-008 — OCR engine: ONNX PaddleOCR mobile, recognition-only, OCV-first
**Date:** 2026-06-06 · **Status:** Accepted
**Decision:** Base OCR/OCV engine = PaddleOCR PP-OCR **mobile** recognition model, exported to **ONNX**, **INT8-quantized**, run recognition-only on the cropped ROI and compared to the expected string.
**Why:** Lightest/fastest option for CPU-only at 1000 img/min; OCV (known expected text) lets us skip detection (~2–3× faster). See [engine doc](../05-ocr-ocv-engine.md).
**Consequence:** A neural model ships in the base product → must be locked & versioned (see D-007).

## D-007 — Neural OCR must be a locked, versioned, validated model
**Date:** 2026-06-06 · **Status:** Accepted
**Decision:** Pin one ONNX model version (sha256 in a ModelVersion registry), log model version with every result, treat any model swap as a change-control/revalidation event.
**Why:** Regulators require a fixed validated state; continuous-learning AI is disfavored (FDA PCCP, GAMP 5 2nd ed).
**Note:** Distinguishes the **base locked OCR** from the **optional adaptive AI module**.

## D-006 — CPU-only is the hardware baseline
**Date:** 2026-06-06 · **Status:** Accepted
Most install sites have CPU only. GPU is an optional accelerator, never required. Drives the quantization/model-size strategy.

## D-005 — Throughput target: 1000 images/min, ~1 read/image
**Date:** 2026-06-06 · **Status:** Accepted
~17 ops/sec, ~60 ms/image budget. Comfortable on CPU with the chosen engine.

## D-004 — AI is an optional, licensed, validated module
**Date:** 2026-06-06 · **Status:** Accepted
**Decision:** Built from day one but as a pluggable, feature-flag/licensed module; the classic-vision core works fully standalone. AI = trainable/adaptive tools (DL-OCR for hard codes, anomaly detection).
**Why:** Only some customers need/buy AI; keeps base hardware cheap (no mandatory GPU) and simplifies base validation.
**Consequence:** All inspection tools (classic & AI) implement one common interface; licensing tiers Base / AI / Serialization.

## D-003 — Serialization is Phase 2, but the data model is serialization-ready now
**Date:** 2026-06-06 · **Status:** Accepted
**Decision:** Phase 1 = online print/code **verification** only. Phase 2 = serialization + aggregation. But Phase 1 parses GS1 AIs (GTIN/batch/expiry/serial) into structured fields and exposes an internal event bus so Phase 2 slots in without rework.
**Why:** Avoid the expensive retrofit; verification-first ships value fast.

## D-002 — Hybrid architecture: local Qt runtime + web admin/reporting
**Date:** 2026-06-06 · **Status:** Accepted
**Decision:** PySide6/Qt desktop for the real-time line HMI (acquisition, live view, reject I/O); FastAPI backend + browser UI for recipes/admin/reports/audit.
**Why:** Real-time camera/overlay/reject must be local & fast; reporting/admin benefit from a no-install browser UI. Pure-web is a poor fit for the runtime.

## D-001 — Pharma-first, GigE Vision, Python, compliance-first
**Date:** 2026-06-06 · **Status:** Accepted
Target pharma (regulated) first; vendor-neutral GigE Vision/GenICam acquisition; Python stack; 21 CFR Part 11 / Annex 11 designed in from day one. Positioning: the "missing middle" between general MV platforms and closed pharma specialists.
