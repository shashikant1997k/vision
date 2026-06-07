# Validation Package

Validation artifacts for deploying this system in a GxP / 21 CFR Part 11 / EU GMP
Annex 11 environment. These are **templates/drafts** to be reviewed, approved, and
executed by the customer's QA/validation team for each installation — software is
made compliant by a *validated installation*, not by the code alone.

| Doc | Purpose |
|---|---|
| [01 — Validation Plan](01-validation-plan.md) | Scope, GAMP 5 category, approach, roles, deliverables |
| [02 — Installation Qualification (IQ)](02-iq.md) | Prerequisites + install verification checklist |
| [03 — Operational Qualification (OQ)](03-oq.md) | Test cases proving the system works to spec |
| [04 — 21 CFR Part 11 / Annex 11 Compliance Matrix](04-part11-compliance-matrix.md) | Each regulatory clause → implementation → evidence |
| [05 — Traceability Matrix](05-traceability-matrix.md) | Requirement → design → automated test |

## Evidence base

The product ships an **automated test suite (83 tests)** that exercises the
compliance-critical behaviour (audit trail, e-signatures, RBAC, code/OCR
verification, reject, batch, reporting). OQ test cases reference these tests as
supporting evidence; they are re-run as part of regression and re-qualification.

Run the suite (OQ evidence):

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q          # headless
python -m pytest -q --junitxml=oq-evidence.xml         # machine-readable evidence
```

## Re-qualification triggers (per [D-012], [D-013])

Re-run the relevant OQ tests and review the change under change control after:
software upgrade, configuration change, hardware migration, **AI/OCR model
version change** (the model is locked and versioned), or a change of intended use.
