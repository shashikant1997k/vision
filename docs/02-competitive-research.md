# 02 — Competitive Research (verified findings)

Two deep, multi-source research passes (each ~100+ agents, sources adversarially verified — claims needed independent corroboration to survive). **All performance/accuracy figures from vendor pages are marketing (feature-existence, not benchmarks) and are treated as untrusted.**

## The market splits in two — neither serves regulated print inspection well

| Camp | Examples | Strength | Weakness |
|---|---|---|---|
| **General MV platforms** | Cognex In-Sight/ViDi/D900, Zebra Aurora, MVTec HALCON, Overview.ai | Excellent AI/vision tech (edge DL-OCR, anomaly detection, code grading) | **Not turnkey-validated for pharma** — Part 11, IQ/OQ, serialization left to integrator |
| **Pharma specialists** | SEA Vision, Lake Image (DISCOVERY PharmaPQ) | Bundle GMP/Part 11 + Annex 11, IQ/OQ docs, audit files, T&T reconciliation | Older/closed tech, less modern AI, expensive |

**The opportunity = the "missing middle":** modern, explainable AI tooling **with** built-in, validation-ready pharma compliance.

## Vendor coverage (verified, primary sources)

- **Cognex** — most explicit pharma compliance among general vendors. In-Sight Track & Trace provides Part 11 technical controls (secure auth, automatic audit-trail generation, multi-level/role permissions). Reads Data Matrix, GS1-128, securPharm, GS1 DataBar, Pharmacode. Edge DL inference on D900 (embedded ViDi) / In-Sight 2800. Controls enable validation; **the end user still validates**.
- **Keyence (CV-X/XG-X)** — AI-assisted trainable-dictionary OCR for lot/batch/expiry on varied/etched/low-contrast/curved surfaces; reads Pharmacode, Data Matrix ECC200, GS1; ISO 15415/15416 grading. Premium, closed ecosystem.
- **Hikrobot VisionMaster** — DL-OCR for low-contrast/deformed/complex-background characters + 1D/2D multi-format reading. Product page is **silent on Part 11, ISO grading, GigE Vision, SDK, licensing** (GigE exists on its camera/MVS-SDK pages — a positioning gap). Value-tier tech, weak compliance story.
- **Omron LVS verifiers** (9510 desktop / 9580 paper-label / 9585 DPM) — **the baseline bar**: built-in 21 CFR Part 11 User Administration + Audit Trail (DB-stored); offline GS1/HIBC/USPS + ISO 15415/15416 grading. A dedicated verifier ships Part 11 built-in — so must we.

## Verified table-stakes (must-haves to be credible)

**Code reading & grading**
- Read pharma symbologies: GS1 DataMatrix, GS1-128, GS1 DataBar, securPharm, Pharmacode.
- **Grade** per ISO/IEC 15415 (2D) and 15416 (1D) — not just read. Overall grade = the **lowest** parameter grade; a GS1 grade fails if **any** GS1 parameter fails. Log a numeric grade per code.
- Parse GS1 Application Identifiers (01 GTIN, 10 batch, 17 expiry, 21 serial) into structured fields.

**21 CFR Part 11 / Annex 11 (concrete, mandatory)**
- Audit trail: secure, time-stamped, **read-only, no deletion by anyone**, who/what/when for every change.
- Electronic signatures: two components (unique User ID + private password), uniquely linked to one person, never reassigned.
- Role-based access control.
- IQ/OQ validation documentation; data integrity (ALCOA+).

## Verified AI baseline (for the optional module)

- **Pretrained deep-learning OCR** reading deformed/dot-matrix/low-contrast codes **without font teaching**.
- **Unsupervised anomaly detection** trained on good images only.
- Inference may run on-device, but **model training happens offline on a PC**.

## The exploitable weaknesses (verified against peer-reviewed papers / ISPE / FDA guidance)

1. **Black-box AI opacity undermines auditability** under GMP/Part 11; regulators & experts prefer **inspectable/explainable** models (XAI).
2. **Continuous-learning AI conflicts with a fixed validated state.** Mandated pattern: **locked/static model**, retrained only under formal change control; each retrain = a controlled change re-running validation. (FDA PCCP guidance Dec 2024; GAMP 5 2nd ed; Good ML Practice.)
3. **Revalidation is triggered by any significant change** (software, config, hardware, intended use) → change-control is a recurring pain.
4. **Sensitivity vs. false-reject is a perennial unsolved tuning problem** (rule-based systems can exceed 30% false-reject on hard product).
5. **53% of pharma firms lack internal AI expertise** (RAPS/Celegence 2024) → demand for guided, self-serve tooling + bundled validation.

## Honest caveats / what did NOT verify

- **Vendor-specific named complaints** (Cognex dongles/licensing, OCRMax tuning pain, Keyence closed SDK, etc.) **did not survive verification** — one Cognex false-reject case study was refuted 0-3. Treat "incumbents are expensive/closed/hard to integrate" as a **working hypothesis to confirm via direct integrator/customer interviews**, not established fact.
- Regulatory landscape is moving (FDA CSA final Sept 2025, EU GMP Annex 22 draft, GAMP 5 2nd ed) — re-check as guidance finalizes.

## Coverage still thin (see research backlog)

MVTec HALCON, Zebra Aurora, SEA Vision and Lake Image pharma positioning; concrete SDK-openness / licensing facts per vendor; real-world throughput & false-reject numbers. See [Research Backlog](07-research-backlog.md).
