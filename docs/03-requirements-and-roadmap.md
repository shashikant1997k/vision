# 03 — Requirements & Roadmap

Guiding rule: **everything in Phase 1 must be serialization-ready and compliance-built-in** — retrofitting those is the expensive mistake.

## Phase 1 — MVP: "Inline print & code verifier, validated"

The must-ship core that makes us credible and deployable on a real pharma line.

### Acquisition & runtime
- [ ] GigE Vision / GenICam acquisition (vendor-neutral), **multi-camera** (N cameras per line PC, each independent).
- [ ] Hardware / encoder trigger; software trigger for setup.
- [ ] Camera controls: exposure, gain, white balance, ROI, frame rate, packet size.
- [ ] Basic calibration (pixel ↔ mm).
- [ ] Live mode with result overlays + running pass/fail/reject counters (per camera).
- [ ] **Multi-product-in-one-FOV (track-to-region mapping):** N products per frame, each its own Region with its own ROIs/tools and pass/fail.
- [ ] **Per-region reject routing** to the correct lane/output, with per-lane eject timing; last-reject image review.

### Inspection tools (classic — the revenue core)
- [x] **OCR/OCV** for fixed + variable text (lot, expiry, MRP) — *done: ONNX PaddleOCR/RapidOCR, exact/contains/regex matching; INT8 rec-only throughput path still TODO*.
- [ ] **1D/2D code read + verify** — GS1 DataMatrix, GS1-128, QR, DataBar, Pharmacode — decode + **content verification** (GTIN/batch/expiry/serial match expected).
- [ ] **Inline approximate ISO 15415/15416 quality metrics** — logged as **"process-control grade, not certified"** (certified grading = sampling workflow with a verifier; see [D-012](decisions/decision-log.md)).
- [ ] **GS1 AI parsing** (01/10/17/21 → structured fields). *Serialization-ready hook.*
- [ ] Presence/absence + pattern-match fixturing (locate-then-inspect).
- [ ] Per-tool tolerances + AND/OR pass/fail logic.

### Recipe / product
- [ ] Product = recipe (camera settings + **regions** + per-region tools + tolerances + pass/fail logic).
- [ ] **Regions/tracks:** define N product positions in a camera FOV; each region maps to a reject lane.
- [ ] **Multi-camera assignment:** bind each camera on the station to a recipe for a batch.
- [ ] **Recipe versioning + change control + e-signature approval** (draft → approved → retired).
- [ ] Two-tier teach UI: guided wizard (QA operators) + advanced (role-gated).
- [ ] Recipe clone / import / export.

### External integration
- [ ] **TCP/IP result publishing to third-party apps** — configurable TCP server/client, JSON or delimited format, real-time push per result, store-and-forward + auto-reconnect (D-014).

### Compliance (non-negotiable, day one)
- [x] RBAC (roles + rights), secure login, password policy — *done (lockout incl.); idle logout still TODO*.
- [x] **Read-only, no-delete, time-stamped audit trail** (who/what/when, old→new) — *done: hash-chained + tamper-evident*.
- [x] **Two-component electronic signatures** on recipe approval — *done (identity + password re-entry); batch release TODO*.
- [ ] Data integrity (ALCOA+); image archival policy & retention.

### Batch & reporting
- [x] Batch create / start / close (release e-signature); variable data per batch — *done; pause/resume TODO*.
- [x] Counters by reject reason (rejects by lane, defects-by-tool Pareto) — *done*.
- [x] Batch report (CSV + signed HTML): counts, defect Pareto, sign-off — *done; PDF + sample fail images TODO*.

### Architecture foundations (invisible but critical)
- [ ] Plugin "inspection tool" interface (AI tools drop in identically later).
- [ ] Internal result/event bus (serialization subscribes in Phase 2).
- [ ] Feature-flag / licensing gate (Base / AI / Serialization tiers).
- [ ] Locked-model registry (pin OCR model version, log with every result).

## Phase 2 — AI module (optional, licensed) + serialization

### AI module
- [ ] Pretrained DL-OCR (dot-matrix / CIJ / curved) — locked-model lifecycle.
- [ ] Unsupervised anomaly detection (train on good images only).
- [ ] Explainable + human-override; model version + confidence logged per result.
- [ ] Nuisance-reject retraining workflow (retrain from rejected images).

### Serialization & aggregation
- [ ] Serial number management.
- [ ] Parent-child aggregation (item → bundle → case → pallet).
- [ ] L3/L4 reporting per market (India CDSCO/DGFT, EU FMD, US DSCSA).

> **Note:** Multi-camera and multi-product-in-one-FOV were **moved to Phase 1** (see decision D-010).

## Phase 3 — Enterprise & scale

- [ ] Fleet / central management (multi-station config push, health monitoring). *Differentiator — no incumbent fleet product does this with OCR + grading + Part 11.*
- [ ] MES/ERP integration; PLC/fieldbus depth (Profinet, EtherNet/IP, OPC-UA).
- [ ] LDAP / SSO; maker-checker workflows.
- [ ] Advanced analytics / OEE; multi-language.

## Open phasing decisions

See [Research Backlog](07-research-backlog.md) — notably: does any early customer need AI *in the first release*, and is multi-camera/multi-product required in the MVP (currently Phase 2)?
