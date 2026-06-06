# 06 — Compliance (21 CFR Part 11 / EU GMP Annex 11)

The product is built **compliance-first**. These are design requirements, not features to bolt on. A system is never "compliant" by itself — it is **validatable**, and compliance is achieved through a validated installation. Our job is to provide the technical controls and the documentation that make validation straightforward.

## Mandatory technical controls (verified requirements)

### Audit trail — 21 CFR 11.10(e)
- **Secure, time-stamped, computer-generated** record of who/what/when for **every** create/modify action.
- **Read-only and append-only** — no user (including admins) can delete or alter entries.
- Captures **old value → new value** for changes.
- Independently retrievable and exportable (CSV / report) for inspection.
- Implementation: `AuditEntry` table, write-only at the DB layer (no UPDATE/DELETE grants), with integrity protection.

### Electronic signatures — 21 CFR 11.50 / 11.100 / 11.200
- **Two distinct components**: a unique User ID + a private password.
- **Uniquely linked to one individual**; never reused or reassigned.
- Each signature records the **meaning** (e.g. "approved", "released"), the signer, and the timestamp.
- Applied at minimum to: **recipe approval** and **batch release**.
- Implementation: `ESignature` table; signature events also written to the audit trail.

### Access control (RBAC) — 11.10(d) / Annex 11
- Users only perform actions their role/training permits.
- Roles, permissions, user-role assignment; secure login, password policy, account lockout, idle auto-logout.

### Data integrity — ALCOA+
Data must be **A**ttributable, **L**egible, **C**ontemporaneous, **O**riginal, **A**ccurate (+ Complete, Consistent, Enduring, Available). Inspection results, images, and decisions are recorded contemporaneously, attributed to user/recipe/model version, and retained per policy.

## Barcode grading: inline vs. certified (important claims distinction)

**Verified:** a *certified* ISO/IEC 15415 (2D) / 15416 (1D) grade requires a **conformant verifier** — calibrated hardware, certified test cards, matched optical aperture, per **ISO/IEC 15426-1/-2:2023**. **Software/an inline camera cannot produce a certified grade**, only an approximate one. (There is no universal "660 nm / 45°" lighting rule — that was refuted; illumination is required but geometry varies.)

To stay compliant and honest:

- **Inline (100% inspection):** decode + **content verification** + **approximate ISO-style quality metrics** — always labeled **"process-control grade, not a certified verifier grade."** Never market inline output as a certified ISO grade.
- **Certified grading:** support a **sampling / offline QA workflow** using a real verifier (Omron LVS, Axicon, Cognex DataMan verifier). Record or import verifier results into the batch record; optional verifier-SDK integration later.

This protects the customer's regulatory claims and is itself a trust differentiator. See decision [D-012](decisions/decision-log.md).

## AI-specific compliance (when the optional module is enabled)

The research is explicit: regulators treat **continuously-learning AI** with skepticism and traditional validation breaks for adaptive models. Therefore:

- **Locked / static models only** in production. The model is a validated artifact, versioned by `sha256`.
- **Each retraining is a controlled change** that re-runs the relevant validation steps (FDA PCCP guidance Dec 2024; GAMP 5 2nd ed; Good ML Practice).
- **Explainability / human-in-the-loop** — log model version + confidence per decision; allow human review/override; prefer inspectable behavior over black-box pass/fail.
- **Model version logged with every result** (`ToolResult.model_version_id`) for full traceability.

## Validation support (what we ship to ease IQ/OQ)

- Documented intended use, functional specs, and test cases (bundled validation docs — a key differentiator vs. general MV platforms that leave this to the integrator).
- Installation Qualification (IQ) / Operational Qualification (OQ) templates.
- Configurable, exportable audit & batch reports for inspection readiness.

## Change control (turn the incumbent pain into our strength)

Revalidation is triggered by any significant change. We minimize the friction:

- **Granular recipe versioning** with visual diff (what changed, by whom, when, why).
- **Risk-based** change classification (not every change forces full revalidation).
- Airtight audit trail of the change + e-signature approval workflow (maker-checker in a later phase).

## Notes & caveats

- Regulatory landscape is moving — FDA CSA final (Sept 2025), EU GMP **Annex 22** (AI) draft, **Annex 11** update — re-check as guidance finalizes.
- Target-market serialization rules (India CDSCO/DGFT, EU FMD/EMVS, US DSCSA) are a **Phase-2** concern; confirm target markets before building reporting adapters.
