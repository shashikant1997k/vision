# 04 — 21 CFR Part 11 / EU GMP Annex 11 Compliance Matrix

How the system meets each regulatory control. "Evidence" = the implementing module
and the automated test(s). Procedural controls (SOPs) are the customer's
responsibility and noted as such.

## 21 CFR Part 11 — Subpart B

| Clause | Requirement | How met | Evidence |
|---|---|---|---|
| 11.10(a) | Validation of systems | Bespoke app with full lifecycle + automated suite; this validation package | `docs/validation/*`, 83 tests |
| 11.10(b) | Records in human-readable & electronic form | Signed HTML + CSV batch reports; DB records | `reporting/batch_report.py` · `test_report_export.py` |
| 11.10(c) | Protection of records (retention/retrieval) | DB persistence; images on filesystem (path+checksum); image-retention policy; no-delete audit | `db/`, `runtime/archive.py` · `test_assembler.py` |
| 11.10(d) | Limit access to authorized individuals | Secure login + RBAC | `security/`, `db/users.py` · `test_auth.py` |
| 11.10(e) | Secure, time-stamped audit trail; no obscuring; retained | Append-only **hash-chained** audit (who/what/when/old→new); tamper detected | `db/audit.py` · `test_audit.py` |
| 11.10(f) | Operational system checks (sequencing) | Recipe must be **approved** before a batch starts; draft→approved→retired states | `db/batches.py`, `db/store.py` · `test_batch.py` |
| 11.10(g) | Authority checks | Permission enforced per action (recipe.create/approve, batch.manage, station.manage) | `security/authz.py` · `test_auth.py`, `test_persistence.py` |
| 11.10(h) | Device checks (input source) | Camera/station bound to recipe via CameraAssignment; source identified per frame | `runtime/assembler.py` · `test_assembler.py` |
| 11.10(k) | Controls over documentation/change | Versioned recipes + change control + audit; git-versioned software | `db/store.py` · `test_persistence.py` |

## 21 CFR Part 11 — Subpart C (electronic signatures)

| Clause | Requirement | How met | Evidence |
|---|---|---|---|
| 11.50 | Signature manifestations (name, date/time, meaning) | `ESignature` stores user, timestamp, **meaning**; shown on the batch report | `db/models.py`, `reporting/` · `test_batch.py` |
| 11.70 | Signature/record linking | `audit_entries.signature_id` FK links the signature to the action/record | `db/audit.py`, `db/models.py` |
| 11.100 | Unique to individual, not reused | Unique username; users never deleted/reassigned | `db/users.py` · `test_auth.py` |
| 11.200 | Signature components & controls (two components; re-auth) | Two components (User ID + password); **password re-entry at signing** for approve/release | `db/store.py`, `db/batches.py` · `test_persistence.py`, `test_batch.py` |
| 11.300 | Controls for ID codes/passwords (uniqueness, aging, lockout) | PBKDF2 hashing (no plaintext), password policy, **lockout after 5 failures** | `security/passwords.py`, `db/users.py` · `test_auth.py` |

## EU GMP Annex 11 (key clauses)

| Clause | Requirement | How met | Evidence |
|---|---|---|---|
| 4 | Validation | This package + automated suite | `docs/validation/*` |
| 7.1 | Data storage/protection & accuracy | DB + checksummed image archive; verified reads logged with grade | `db/`, `runtime/archive.py` |
| 9 | Audit trails | Hash-chained append-only audit, reviewable | `db/audit.py` · `test_audit.py` |
| 12.1 | Access control | RBAC + authentication | `security/` · `test_auth.py` |
| 12.4 | Authority by role | Role permissions enforced | `security/authz.py` |
| 14 | Electronic signatures | Two-component e-signatures with meaning | `db/` · `test_batch.py` |
| 15 | Batch release | Batch release is an e-signed, audited action; signed report produced | `db/batches.py`, `reporting/` |

## Customer (procedural) responsibilities

SOPs for: user provisioning/de-provisioning & periodic access review, password
policy parameters, audit-trail review frequency, data backup & retention, change
control, training records, and periodic re-qualification. Technical controls above
**enable** compliance; a validated, SOP-governed installation **achieves** it.
