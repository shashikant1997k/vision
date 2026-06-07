# 01 — Validation Plan

## 1. Purpose & scope

Defines the approach to validate the Vision Inspection System for use in a
regulated (GxP / 21 CFR Part 11 / EU GMP Annex 11) pharmaceutical packaging line.
Scope = the inline print & code verification application: acquisition, inspection
(OCR/OCV + 1D/2D code verification & grading), reject control, recipe/batch
management, users/audit/e-signatures, and reporting.

Out of scope (this release): serialization/aggregation (Phase 2), the web
reporting UI, and any customer-side network/infrastructure validation.

## 2. System classification (GAMP 5)

**Category 5 — bespoke (custom) application.** The inspection logic and data model
are purpose-built, so the full software lifecycle applies: requirements, design,
implementation with version control, automated testing, and IQ/OQ/PQ.

Supporting infrastructure (PostgreSQL, OS, GenTL producer, ONNX Runtime) is
**Category 1 (infrastructure software)** — qualified by installation and supplier
documentation.

## 3. Validation approach (risk-based, FDA CSA-aligned)

- **Requirements** are captured in [docs/03](../03-requirements-and-roadmap.md) and
  the [decision log](../decisions/decision-log.md).
- **Design** is documented in [architecture](../04-system-architecture.md),
  [engine](../05-ocr-ocv-engine.md), [compliance](../06-compliance.md),
  [data & audit](../09-data-and-audit.md), and [camera module](../10-camera-module.md).
- **Verification** = an automated test suite (83 tests) plus the OQ test cases in
  [03-oq](03-oq.md); critical, patient-impacting functions (code/OCR verify,
  reject, audit, e-signature) get the most coverage.
- **Traceability** requirement → design → test is in [05](05-traceability-matrix.md).
- **Data integrity (ALCOA+)** is designed in: append-only hash-chained audit,
  no-delete records, attributable actions (authenticated users), contemporaneous
  timestamps (NTP), original images archived, accurate reads logged with grade.

## 4. Deliverables

1. This Validation Plan.
2. Installation Qualification (IQ) — executed per installation.
3. Operational Qualification (OQ) — executed per installation; references the
   automated suite as supporting evidence.
4. Performance Qualification (PQ) — **customer-executed** on the live line with
   real product (line-speed throughput, false-reject rate, grade correlation vs a
   certified verifier per [D-012](../decisions/decision-log.md)).
5. 21 CFR Part 11 / Annex 11 compliance matrix.
6. Traceability matrix.

## 5. Roles & responsibilities

| Role | Responsibility |
|---|---|
| Supplier (us) | Software, design docs, automated tests, IQ/OQ templates, support |
| Customer QA | Approve protocols, execute/witness IQ/OQ/PQ, manage change control |
| Customer IT | Provision & qualify PC, OS, PostgreSQL, network, NTP |
| System owner | Define recipes, manage users/roles, run batches |

## 6. Acceptance criteria

System is released for GxP use when IQ + OQ are executed with all critical test
cases **Pass**, deviations are resolved/justified, the Part 11 matrix is complete,
and QA signs the validation summary report.

## 7. Maintenance & re-qualification

Under change control; re-run impacted OQ tests after any significant change
(software upgrade, config change, hardware migration, **locked OCR/AI model
version change**, changed intended use). See [validation README](README.md).
