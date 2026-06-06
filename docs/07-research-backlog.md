# 07 — Open Questions & Research Backlog

Living list. We document and build in parallel with research. Priority: **P1** (blocks a near-term decision) · **P2** (shapes design soon) · **P3** (good to know).

## Product / commercial decisions (need user/customer input)

- [ ] **P1 — Does any early customer need the AI module in the first release?** Currently AI is Phase 2 (optional). If a flagship customer needs DL-OCR on day one, pull it forward.
- [x] **P1 — Is multi-camera / multi-product-in-one-FOV required in the MVP?** ✅ **YES (2026-06-07)** — moved to Phase 1 (decision D-010). Recipe → Regions → Tools; per-lane reject routing.
- [ ] **P1 — Multi-product/multi-camera throughput on CPU-only.** Config confirmed (2026-06-07): C=2–3 typ/4 max cameras, P=2–3 typ/4 max products/FOV, R≈5–8 ROIs/product (4–7 text + 1 code). Analysis: typical ~220 ops/s (comfortable on 8-core), worst-case-maxed ~530 ops/s (needs 12–16 core or GPU). **Still need: line speed (frames/s per camera)** — the binding variable. Validate the whole envelope on a spike.
- [ ] **P1 — Confirm line speed** (products/min or frames/s per camera) for target lines — drives the throughput sizing above.
- [ ] **P2 — Target markets / serialization regimes** (India CDSCO/DGFT, EU FMD/EMVS, US DSCSA). Decides Phase-2 reporting adapters.
- [ ] **P2 — Single station vs. fleet** from the start? Affects whether the data service is per-line or central.
- [ ] **P3 — Licensing/activation mechanism** (online vs. offline dongle/key) for the tier gating.

## Technical research

- [x] **P1 — ISO/IEC 15415/15416 grading: build vs. buy.** ✅ **RESOLVED (2026-06-07):** certified grade needs conformant verifier hardware (ISO 15426); OSS Python libs decode only. Approach = inline approximate "process-control grade" + content verification; certified grading via verifier sampling. See D-012. **Remaining (P2):** which verifier SDKs (Omron LVS / Axicon / Cognex) expose a Python API + licensing; exact inline ISO-parameter set to compute.
- [x] **P1 — GenICam/GigE in Python.** ✅ **RESOLVED (2026-06-07):** Harvester + vendor GenTL producers (vendor SDK fallback). See D-011. **Remaining spikes (P1):** (a) multi-vendor `.cti` producer interop on a Windows box; (b) sustain ~1000+/min + encoder-to-reject latency benchmark.
- [ ] **P2 — PaddleOCR PP-OCR mobile → ONNX → INT8**: confirm export path, measure real latency/accuracy on representative pharma CIJ/dot-matrix samples on a target CPU.
- [ ] **P2 — 1D/2D decode libs**: libdmtx vs. ZXing vs. zbar — accuracy on GS1 DataMatrix, securPharm, Pharmacode; licensing.
- [ ] **P2 — Reject timing model**: encoder-based product tracking from inspection point to reject actuator; double-reject handling.
- [ ] **P2 — Append-only audit at the DB layer**: Postgres patterns (revoke UPDATE/DELETE, triggers, hash-chaining for tamper evidence).
- [ ] **P3 — Anomaly-detection approach** for the AI module (e.g. PatchCore/PaDiM-style, normal-only training) and its validation story.

## Competitive research still thin (from research passes)

- [ ] **P2 — MVTec HALCON, Zebra Aurora, SEA Vision, Lake Image** pharma positioning & documented limitations (no confirmed findings yet).
- [ ] **P2 — Verify the "incumbents are expensive/closed/hard to integrate" hypothesis** with direct integrator/customer interviews — forum/review evidence did NOT survive verification.
- [ ] **P3 — Per-vendor SDK openness & Python support** (Cognex VisionPro/OCRMax/DataMan, Keyence, Hikrobot MVS) and whether Part 11 / audit / e-sign are paid add-on modules.
- [ ] **P3 — Real-world throughput & false-reject numbers** at pharma line speeds.

## Regulatory watch (re-check as guidance finalizes)

- [ ] **P2 — EU GMP Annex 22 (AI)** draft → final.
- [ ] **P2 — EU GMP Annex 11** update.
- [ ] **P3 — FDA CSA** guidance (final Sept 2025) implications for risk-based validation.

## How we work this backlog

Use the deep-research workflow for external/market questions; spikes/prototypes for technical ones. Promote answered items into the relevant doc + a decision-log entry, then check them off here.
