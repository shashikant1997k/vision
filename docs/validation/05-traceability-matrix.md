# 05 — Traceability Matrix

Requirement → design → implementation → verification. Requirement IDs reference
[docs/03 — Requirements & Roadmap](../03-requirements-and-roadmap.md) (Phase 1) and
the [decision log](../decisions/decision-log.md).

| Req | Requirement | Design doc | Implementation | OQ / Test |
|---|---|---|---|---|
| R-01 | GigE Vision / GenICam acquisition (vendor-neutral) | [04](../04-system-architecture.md), [10](../10-camera-module.md), D-011 | `camera/genicam.py`, `camera/device.py`, `camera/discovery.py` | OQ-11 · `test_camera.py` |
| R-02 | Multi-camera + multi-product-in-FOV | [04](../04-system-architecture.md), D-010 | `runtime/runner.py`, `engine/aggregator.py` | OQ-08 · `test_runtime.py`, `test_sim.py` |
| R-03 | OCR/OCV text (lot/expiry/MRP) | [05](../05-ocr-ocv-engine.md) | `tools/ocr.py` | OQ-07 · `test_ocr.py` |
| R-04 | 1D/2D code read + GS1 verify + grade | [02](../02-competitive-research.md), [06](../06-compliance.md), D-012 | `tools/code_verify.py`, `tools/gs1.py`, `tools/grading.py` | OQ-06 · `test_code_verify.py`, `test_gs1.py` |
| R-05 | Versioned recipes + change control + e-sign approval | [09](../09-data-and-audit.md) | `db/store.py` (RecipeRepository) | OQ-04/05 · `test_persistence.py`, `test_recipe_load.py` |
| R-06 | Users / RBAC / login / lockout | [06](../06-compliance.md) | `security/`, `db/users.py` | OQ-01/02 · `test_auth.py` |
| R-07 | Append-only, tamper-evident audit trail | [09](../09-data-and-audit.md) | `db/audit.py` | OQ-03 · `test_audit.py` |
| R-08 | Two-component electronic signatures | [06](../06-compliance.md) | `db/store.py`, `db/batches.py`, `hmi/approve_dialog.py` | OQ-04 · `test_batch.py`, `test_teach.py` |
| R-09 | Batch lifecycle + signed report | [09](../09-data-and-audit.md) | `db/batches.py`, `reporting/batch_report.py` | OQ-10 · `test_batch.py`, `test_report_export.py` |
| R-10 | Per-lane reject routing + eject timing | [04](../04-system-architecture.md) | `io/reject.py`, `io/digital_io.py` | OQ-09 · `test_reject_io.py` |
| R-11 | Camera settings, calibration, focus-assist | [10](../10-camera-module.md) | `camera/settings.py`, `camera/calibration.py`, `camera/focus.py`, `hmi/settings_window.py` | OQ-11 · `test_camera.py`, `test_settings_screen.py` |
| R-12 | Station/camera/reject config persisted + audited | [04](../04-system-architecture.md), D-013 | `db/stations.py` | OQ-11 · `test_stations.py` |
| R-13 | Load-station → run-batch + frame archive | [04](../04-system-architecture.md) | `runtime/assembler.py`, `runtime/archive.py` | OQ-12/14 · `test_assembler.py`, `test_live_batch.py` |
| R-14 | External TCP/IP result publishing | [04](../04-system-architecture.md), D-014 | `integrations/` | (Phase-1 interface) · `test_integration.py` |
| R-15 | HMI: login / teach / settings / live | [08](../08-project-structure.md), D-015 | `hmi/` | OQ-13 · `test_hmi.py`, `test_teach.py`, `test_live_batch.py` |
| R-16 | PostgreSQL + JSONB persistence; images on FS | [09](../09-data-and-audit.md), D-013 | `db/base.py`, `db/models.py` | OQ-10/14 · `test_persistence.py` |
| R-17 | Locked, versioned OCR/AI model | [05](../05-ocr-ocv-engine.md), D-007/D-012 | `models/registry.py`, `tools/ocr.py` | IQ-C6 (model pinned) |

## Deferred (Phase 2 / out of scope this release)

| Req | Requirement | Status |
|---|---|---|
| R-P2-1 | Serialization & aggregation (GS1, parent-child, L3/L4) | Data model is serialization-ready (CodeRead AIs); feature deferred |
| R-P2-2 | Optional AI module (DL-OCR/anomaly) train→lock→validate→deploy | Locked-model pattern in place; training UI deferred |
| R-P2-3 | Web reporting/admin UI | Deferred (desktop HMI is the line UI, D-015) |
| R-P2-4 | Certified ISO grading integration (verifier SDK) | Sampling workflow per D-012 |
