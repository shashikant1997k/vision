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
│   ├── base.py      # InspectionTool ABC + ToolResult — the ONE interface all tools implement (D-004)
│   ├── registry.py  # type -> tool class; build_tool()
│   └── stub_ocv.py  # placeholder OCV tool (→ ONNX PaddleOCR in Phase 1, docs/05)
├── domain/
│   └── entities.py  # Recipe -> Region -> ToolSpec (multi-product, D-010); CameraConfig
├── engine/
│   ├── frame.py     # Frame (image + provenance)
│   ├── camera.py    # Camera ABC + FakeCamera (→ Harvester/GenICam in Phase 1, D-011)
│   ├── workers.py   # ToolTask / ToolOutcome + run_tool_task() (warm per-process tool cache)
│   ├── pool.py      # SyncPool (in-process) and ProcessPool (multiprocessing, docs/05)
│   ├── aggregator.py# group tool outcomes -> per-region pass/fail + reject routing
│   └── pipeline.py  # frame -> crop -> pool -> aggregate -> publish results/rejects
├── models/
│   └── registry.py  # ModelRegistry — locked, hashed, versioned models (D-007)
└── cli.py           # build_demo_recipe() + runnable demo entrypoint
tests/
├── test_tools.py    # tool interface + registry
└── test_pipeline.py # end-to-end pipeline (all-pass and all-reject)
```

## The seams (where real implementations drop in)

| Seam | Skeleton today | Phase-1 real implementation |
|---|---|---|
| `engine/camera.py` | `FakeCamera` generates synthetic frames | GenICam/Harvester GigE acquisition, 1 process per camera (D-011) |
| `tools/stub_ocv.py` | reads a pixel value | ONNX PaddleOCR mobile, recognition-only OCV (docs/05) |
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
