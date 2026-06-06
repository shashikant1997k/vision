# 04 — System Architecture

> Draft v0.1 — to be refined as we build. Captures the agreed shape; specifics (DB choice, GenICam library) are recommendations pending validation.

## The 5 layers

1. **Acquisition / hardware** — camera, lens, lighting, trigger, encoder, I/O. GenICam / GigE Vision.
2. **Inspection engine** — frame → pass/fail + measurements (OCV/OCR, code read & grade, presence). See [Engine doc](05-ocr-ocv-engine.md).
3. **Recipe / job layer** — versioned configuration that drives the engine.
4. **Runtime / line layer** — live execution, triggering, reject control, PLC handshake.
5. **Enterprise layer** — users, audit, batches, reports, (Phase 2) serialization, integration.

## Deployment topology

Hybrid: a **local desktop/service on the line PC** owns everything real-time; a **web layer** (can be local-hosted or central) owns reporting/admin.

```
            LINE PC (Windows, industrial)
 ┌───────────────────────────────────────────────────────┐
 │  HMI process (PySide6/Qt)                              │
 │    live view, overlays, operator actions, teach UI    │
 │            ▲            │                               │
 │   results  │            │ commands                      │
 │            │            ▼                               │
 │  ┌─────────────────  Engine subsystem  ──────────────┐ │
 │  │ Acquisition procs (1 per camera) → shared-mem ring│ │
 │  │ Dispatcher: per frame, per Region → crop ROIs     │ │
 │  │ OCR worker pool (N procs, warm ONNX sessions)     │ │
 │  │ Code read+grade workers                           │ │
 │  │ Aggregator: per Region → pass/fail →              │ │
 │  │   route to that Region's RejectOutput/lane (I/O)  │ │
 │  └───────────────────────────────────────────────────┘ │
 │            │                                            │
 │            ▼                                            │
 │  Local data service (FastAPI) ── DB (Postgres)         │
 │     recipes, batches, results, audit, users            │
 └───────────────────────────────────────────────────────┘
              │ HTTP (LAN)
              ▼
   Browser UI (admin, recipes, batch reports, audit export)
   — operators on the line use the Qt HMI; managers/QA use the web UI
```

**Why hybrid:** real-time frame grab + overlay + reject timing must be **local and fast** (Qt desktop). Reporting/admin/recipe management benefit from a **browser UI** (no per-client install, central access). Both talk to the same local data service.

## Process boundaries (and why)

| Process | Responsibility | Why separate |
|---|---|---|
| **HMI (Qt)** | UI, live view (multi-camera feeds), operator input | UI must stay responsive; never blocked by inference |
| **Acquisition (1 per camera)** | GigE grab → shared memory | Isolate per-camera I/O timing jitter; cameras run independently |
| **OCR worker pool (shared)** | CPU-bound inference for all cameras/regions | Bypass the GIL; scale by core count; pooled across cameras |
| **Data service (FastAPI)** | Persistence, audit, API, web backend | Single writer to the audit store; serves web UI |

Frames move via **shared memory**; only small handles/ROIs cross queues. The OCR worker pool is **shared across all cameras and regions** (not per-camera) so cores are used efficiently. See engine doc for the throughput rationale.

## Tech stack (recommended, pending validation)

| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.11+** | Per requirement |
| Line HMI | **PySide6 (Qt)** | Mature, native-feeling industrial HMI; good image display |
| Acquisition | **GenICam via Harvester** (`.cti` GigE Vision producer) | Vendor-neutral; vendor SDK as fallback for advanced features |
| Image ops | **OpenCV** | Crop, preprocess, overlay |
| OCR/OCV | **ONNX Runtime + PaddleOCR (PP-OCR mobile, INT8)** | CPU-first; see engine doc |
| 1D/2D decode | **libdmtx / ZXing / zbar** + ISO 15415/15416 grading (lib or in-house) | Grading is a real algorithm, not just decode |
| Backend/API | **FastAPI** | Async, typed, serves web UI + internal API |
| Web UI | **React** (or server-rendered) | Admin, recipes, reports, audit |
| Database | **PostgreSQL + JSONB**, via SQLAlchemy + Alembic | DB-level append-only audit; JSONB for variable configs; SQLite for tests only (D-013) |
| External integration | **TCP/IP result publishing** (server/client, JSON or delimited) | Push scanned data to any third-party app; via EventBus (D-014) |
| IPC | `multiprocessing` + `shared_memory` + bounded queues | Same-host, low latency |
| Reject / PLC | Digital I/O card / **Modbus TCP** first; Profinet/EtherNet-IP/OPC-UA later | |
| Packaging | PyInstaller / MSI for the line PC | Offline install |

## Data model (serialization-ready from day one)

Core entities (relational):

- **User** (id, username, password_hash, full_name, status, last_login)
- **Role** (id, name) — **Permission** (id, code) — **RolePermission**, **UserRole**
- **Station** (id, name, line) — a line PC's set of cameras + reject outputs
- **Camera** (id, station_id, name, model, identifier [IP/serial], position, default_settings_json)
- **RejectOutput** (id, station_id, name, lane_index, io_channel, eject_delay_ms) — one physical ejector / lane
- **Product** (id, name, code, description, created_by)
- **Recipe** (id, product_id, **version**, **status** [draft/approved/retired], created_by, approved_by, approved_signature_id) — *versioned; immutable once approved*
- **CameraSetting** (recipe_id, camera_role, exposure, gain, wb, frame_rate, trigger_cfg)
- **Region** (id, recipe_id, name, index, fixture_config_json, reject_output_id) — **a single product position within one camera FOV (a "track"/"lane"); a recipe has N regions for N products per frame**
- **InspectionTool** (id, **region_id**, type [ocv/ocr/datamatrix/barcode/presence/pattern], roi [relative to region], config_json, tolerances_json, order)
- **Batch** (id, product_id, station_id, batch_no, mfg_date, exp_date, mrp, variable_data_json, status, started_by, started_at, closed_at)
- **CameraAssignment** (id, batch_id, camera_id, recipe_id, recipe_version) — **binds each camera on the station to a recipe for the run (multi-camera)**
- **FrameCapture** (id, batch_id, camera_id, timestamp, image_ref) — one acquired frame
- **InspectionResult** (id, frame_capture_id, **region_id**, overall_result [pass/fail], reject_reason, reject_output_id) — **one result per product per region; N per frame**
- **ToolResult** (id, inspection_result_id, tool_id, result, measured_value, expected_value, confidence, model_version_id)
- **CodeRead** (id, tool_result_id, symbology, raw_data, **gtin, batch, expiry, serial** ← parsed GS1 AIs) — *Phase-2 serialization reads from here*
- **GradeResult** (id, tool_result_id, iso_standard, overall_grade, parameters_json)
- **AuditEntry** (id, timestamp, user_id, action, entity_type, entity_id, old_value, new_value, signature_id) — **append-only, no delete/update**
- **ESignature** (id, user_id, meaning, timestamp, entity_type, entity_id)
- **ModelVersion** (id, name, file_ref, sha256, validated_by, validated_at) — *locked OCR/AI models*
- **License** (tier, features_enabled_json) — gates Base / AI / Serialization

**Multi-camera / multi-product structure:** `Station → Cameras + RejectOutputs`. A `Recipe → Regions → Tools` (each Region = one product slot in a camera's FOV, mapped to a reject lane). A `Batch` runs on a Station; `CameraAssignment` binds each camera to a recipe. Each `FrameCapture` produces one `InspectionResult` **per Region**, each routed to its `RejectOutput`.

**Phase-2 additions** (no rework to the above): **SerialNumber**, **AggregationUnit** (parent-child) referencing **CodeRead**; reporting adapters per market.

## Licensing tiers (feature-flag gated)

- **Base** — classic OCV/OCR + code read & grade + compliance + batch/reports.
- **+ AI** — DL-OCR, anomaly detection, retraining workflow.
- **+ Serialization** — serial management, aggregation, L3/L4 reporting.

## External integration (data egress)

A configurable integration layer publishes scanned/inspection data to third-party
applications over TCP/IP (D-014). It subscribes to the EventBus, so it is fully
decoupled from the engine.

- **Direction (per connector):** TCP **server** (peer connects to us) or TCP **client** (we connect out).
- **Format:** line-framed JSON (default) or delimited/templated (for host systems).
- **Delivery:** real-time push per inspection result; **store-and-forward** buffer + auto-reconnect.
- **Compliance:** every message logged for audit; connector config is versioned/change-controlled.
- Code in `src/vis/integrations/` (transport + formatter + publisher). Future: OPC-UA, Profinet, EtherNet/IP, MES/ERP.

## Non-functional requirements

- Throughput: total OCR/OCV load = **frames/min × cameras × regions-per-frame × ROIs-per-region** — size the worker pool on *ops*, not frames. CPU-only baseline; see engine doc. (Multi-product/multi-camera multiplies the op count — a key sizing risk, flagged in the backlog.)
- Per-region reject routing with correct **per-lane eject timing** (each region → its own RejectOutput).
- Deterministic backpressure — **never silently skip a product** (log every drop).
- Offline-capable (no internet dependency on the line).
- Restart-safe; no data loss on power cycle (durable writes for audit/results).
