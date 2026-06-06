# 01 — Vision, Scope & Positioning

## Problem

Pharmaceutical lines must verify, at line speed, that every product carries correct and readable coding: lot/batch number, manufacturing & expiry dates, MRP, and machine-readable codes (GS1 DataMatrix, GS1-128, Pharmacode, serialization codes). Errors are a patient-safety and regulatory risk. Verification must be **fast, reliable, and provable** (audit trail, validated system).

## Product vision

An **inline print & code verification system** that:

1. Acquires images from **GigE Vision** cameras as product passes the inspection station.
2. Verifies printed text (OCV) and reads/grades 1D/2D codes against expected values from the batch record.
3. Makes a pass/fail decision and triggers reject in real time.
4. Records every decision in a **tamper-evident, Part 11–compliant** audit trail with full traceability.
5. Lets **plant QA staff configure and approve recipes themselves** after short training, under change control.
6. Optionally applies **explainable AI** (deep-learning OCR for hard codes, anomaly detection) where licensed.

## Target users

- **Plant QA / line operators** — run batches, react to rejects, configure recipes (guided UX).
- **QA managers / supervisors** — approve recipes (e-signature), review batch reports, manage users.
- **Our field engineers / integrators** — commission lines, train customers, advanced setup.
- **Customer IT/validation teams** — IQ/OQ, audit, data integrity oversight.

## Scope

### In scope (product)
- Online print/code **verification** (OCV/OCR, 1D/2D read + ISO grading, presence/absence).
- Recipe/product/batch management with versioning & change control.
- Users, roles, rights; audit trail; electronic signatures.
- Batch reports & analytics.
- Reject control via digital I/O / PLC handshake.
- Optional AI module (licensed).
- **Phase 2:** serialization & aggregation (track & trace).

### Out of scope (for now)
- Generating/managing serial numbers and full L3/L4 track & trace (**Phase 2**).
- General factory automation / non-print vision tasks.
- Robotics / motion control.

## Positioning & differentiation

**One line:** _An open (Python/GigE), compliance-first inline print & code verifier, with explainable AI as an optional validated module, built so plant QA can run change-control themselves._

Differentiators, mapped to verified incumbent weaknesses (see [Competitive Research](02-competitive-research.md)):

| Incumbent weakness (verified) | Our answer |
|---|---|
| Black-box AI undermines auditability | **Explainable, human-confirmable AI**; confidence + model version logged per decision |
| Continuous-learning AI conflicts with validated state | **Locked-model lifecycle**: train → lock → validate → deploy → version |
| Revalidation/change-control friction | **Low-friction, risk-based change control**: granular recipe versioning, visual diff, airtight audit trail |
| Sensitivity vs. false-reject tuning is unsolved | **Nuisance-reject tooling**: review/override workflow, retrain-from-rejected-images, per-tool thresholds |
| 53% of pharma firms lack internal AI expertise | **Guided/no-code teach UX** + bundled validation docs so QA self-serves |
| General platforms aren't turnkey-validated; specialists are closed/expensive | **The missing middle**: modern, open tech **and** built-in compliance |

## Success criteria (initial)

- A line operator can run a batch and react to rejects with no scripting.
- A QA manager can create, version, and e-sign a recipe.
- The system holds 1000 images/min on CPU-only hardware.
- Every config change and inspection decision is auditable and exportable.
- The system is validatable (IQ/OQ) for a Part 11 environment.
