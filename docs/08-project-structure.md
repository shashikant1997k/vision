# 08 — Project Structure (code)

The scaffold establishes the architecture as runnable code: a **walking skeleton**
that runs the full pipeline against a **fake camera**, with the real, hard parts
(GenICam acquisition, ONNX OCR, database, web UI) stubbed behind clean seams.

```
src/vis/
├── common/
│   ├── types.py     # ROI + crop()  (geometry)
│   └── events.py    # EventBus — internal pub/sub; Phase-2 serialization subscribes here (D-003)
├── tools/
│   ├── base.py        # InspectionTool ABC + ToolResult — the ONE interface all tools implement (D-004)
│   ├── registry.py    # type -> tool class; build_tool()
│   ├── stub_ocv.py    # placeholder OCV tool (→ ONNX PaddleOCR in Phase 1, docs/05)
│   ├── code_verify.py # REAL tool: 1D/2D decode + GS1 verify + approximate grade (D-012)
│   ├── ocr.py         # REAL tool: OCV text (lot/expiry/MRP) via ONNX PaddleOCR/RapidOCR (docs/05)
│   ├── decode.py      # zxing-cpp wrapper (reads raw bytes to preserve GS1 0x1d separator)
│   ├── gs1.py         # GS1 Application Identifier parser (01 GTIN / 17 expiry / 10 batch / 21 serial)
│   └── grading.py     # approximate process-control grade (NOT a certified ISO verifier grade)
├── domain/
│   └── entities.py  # Recipe -> Region -> ToolSpec (multi-product, D-010); CameraConfig
├── engine/
│   ├── frame.py     # Frame (image + provenance)
│   ├── camera.py    # Camera ABC + FakeCamera (→ Harvester/GenICam in Phase 1, D-011)
│   ├── sim.py       # SimulatedCodeCamera — renders REAL GS1 codes for demos/tests (dev only)
│   ├── workers.py   # ToolTask / ToolOutcome + run_tool_task() (warm per-process tool cache)
│   ├── pool.py      # SyncPool (in-process) and ProcessPool (multiprocessing, docs/05)
│   ├── aggregator.py# group tool outcomes -> per-region pass/fail + reject routing
│   └── pipeline.py  # frame -> crop -> pool -> aggregate -> publish results/rejects
├── models/
│   └── registry.py  # ModelRegistry — locked, hashed, versioned models (D-007)
├── io/              # reject / digital I/O (ejector driver)
│   ├── digital_io.py # DigitalIO + SimulatedIO (dev/test) + ModbusTcpIO (real line)
│   └── reject.py     # RejectController — eject delay then pulse the lane output
├── camera/          # vendor-neutral camera hardware module (docs/10, D-015)
│   ├── settings.py  # CameraSettings + TriggerConfig (exposure/gain/trigger/ROI)
│   ├── device.py    # CameraDevice ABC + CameraInfo (open/configure/grab/frames)
│   ├── file_source.py # FileCamera — replay images from disk (dev/test on macOS)
│   ├── genicam.py   # HarvesterCamera — real GigE Vision/GenICam driver (Windows)
│   ├── manager.py   # CameraManager — multi-camera lifecycle
│   ├── discovery.py # CameraDiscovery — StaticDiscovery + HarvesterDiscovery (enumerate GigE)
│   ├── lighting.py  # LightController — strobe/continuous; SimulatedLight + DigitalIOLight
│   └── calibration.py # pixel <-> mm
├── security/        # auth + RBAC (Part 11 access control)
│   ├── passwords.py # PBKDF2-HMAC-SHA256 hashing + PasswordPolicy (stdlib, no native deps)
│   └── authz.py     # permission codes, default roles, require()/has_permission()
├── db/              # persistence + audit (docs/09, D-013)
│   ├── base.py      # engine/session factory, Base, JSONType (JSONB on PG)
│   ├── models.py    # ORM models (users, recipes, batches, results, audit, ...)
│   ├── audit.py     # AuditService — append-only, hash-chained, tamper-evident
│   ├── users.py     # UserService — create/authenticate (lockout) + verify_user (e-sign re-auth)
│   ├── batches.py   # BatchService — start (approved recipe) + close (release e-signature)
│   ├── stations.py  # StationRepository — station/camera/reject-output config (RBAC+audited)
│   └── store.py     # ResultStore (persist results) + RecipeRepository (RBAC + e-sign + audited)
├── runtime/         # live run loop (acquisition → pool → reject)
│   ├── runner.py    # InspectionRunner — one acquisition thread per camera
│   ├── stats.py     # LiveStats — thread-safe per-camera + total counters
│   ├── live_view.py # LiveView — latest frame + results per camera (for the HMI)
│   ├── overlay.py   # draw_overlay — annotate frame with ROI boxes + results (HMI view)
│   ├── reject.py    # RejectHandler — reject routing / ejector I/O seam
│   ├── assembler.py # RuntimeAssembler — build a live runner from persisted station config
│   └── archive.py   # FrameArchiver — image-retention policy → FrameCapture rows
├── reporting/
│   └── batch_report.py # compute_summary + CSV export + signed HTML batch report
└── cli.py           # demo recipes + runnable entrypoint (--source, --tcp-server, --db)
alembic/             # PostgreSQL migration scaffolding (env.py wired to Base.metadata)
tests/
├── test_tools.py       # tool interface + registry
├── test_pipeline.py    # end-to-end pipeline (all-pass and all-reject)
├── test_gs1.py         # GS1 AI parser
├── test_code_verify.py # real QR decode + verify + grade
├── test_ocr.py         # real OCR text read + match/regex + pipeline
├── test_camera.py      # camera settings/trigger, FileCamera replay, manager, calibration
├── test_runtime.py     # multi-camera live loop, per-camera stats, reject routing
├── test_discovery_lighting.py # camera discovery + lighting/strobe control
├── test_overlay.py     # annotated-frame rendering (pass green / reject red)
├── test_reject_io.py   # digital I/O pulses, reject controller, ejector lane routing
├── test_sim.py         # simulated code line, multi-product
├── test_audit.py       # audit hash-chain validity + tamper detection
├── test_persistence.py # results persisted; recipe save/approve audited + RBAC-gated
├── test_auth.py        # password hashing/policy, authenticate, lockout, permissions
├── test_batch.py       # batch start/close, results→batch, signed report, audit
├── test_stations.py    # camera-settings + reject-output config persistence, RBAC, audit
└── test_assembler.py   # load-station-run-batch: results→batch, camera assignment, frame archive
```

## The seams (where real implementations drop in)

| Seam | Skeleton today | Phase-1 real implementation |
|---|---|---|
| `engine/camera.py` | `FakeCamera` generates synthetic frames | GenICam/Harvester GigE acquisition, 1 process per camera (D-011) |
| `tools/stub_ocv.py` | reads a pixel value | ONNX PaddleOCR mobile, recognition-only OCV (docs/05) |
| `tools/code_verify.py` | **real** decode + GS1 verify + approx grade | add verifier-SDK integration for certified grading on sampling (D-012) |
| `engine/pool.py` | `ProcessPool` runs stub tools | same pool, warm ONNX sessions loaded in `worker_init()` |
| `domain/entities.py` | in-memory dataclasses | DB-backed, versioned recipes + full data model (docs/04) |
| `common/events.py` | in-process bus | audit sink, reporting, Phase-2 serialization subscribers |
| (none yet) | results printed | PostgreSQL persistence, append-only audit, web UI, reject I/O |

## Design invariants the skeleton already enforces

- **One tool interface** for classic and AI tools (`InspectionTool`) — AI plugs in identically.
- **Crop-first**: only small ROI images cross the process boundary (cheap pickling).
- **Multi-product**: one frame → N `Region` results, each routed to its own reject lane.
- **Pluggable pool**: swap `SyncPool` ↔ `ProcessPool` with no pipeline change.
- **Locked-model traceability**: `ToolResult.model_version` carries which model decided.
