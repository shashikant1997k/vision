# 10 — Camera Module

The vendor-neutral camera hardware layer. Code in `src/vis/camera/`. UI split is
[D-015](decisions/decision-log.md): the line HMI (Qt desktop) drives this module;
the web UI is reporting/admin only.

## Design

One controllable interface, multiple implementations — the runtime/pipeline code
is identical regardless of source:

```
CameraDevice (ABC)        open / close / apply_settings / grab() / frames()
├── FileCamera            replay images from disk (offline test, dev on macOS)
├── HarvesterCamera       real GigE Vision / GenICam via Harvester + .cti (Windows, D-011)
└── (SimulatedCodeCamera) lives in engine/sim.py — renders synthetic codes/text
```

- **`settings.py`** — `CameraSettings` (exposure, gain, frame rate, white balance,
  jumbo `packet_size`, `SensorROI`) and `TriggerConfig` (`TriggerMode`:
  continuous / software / hardware / **encoder** for line tracking). All
  JSON-serialisable → stored in the recipe's `camera_settings`.
- **`device.py`** — `CameraDevice` ABC + `CameraInfo`. Lifecycle (open/close,
  context manager), `apply_settings` (pushes to hardware when open), and
  `frames()` so any device is a pipeline source.
- **`file_source.py`** — `FileCamera`: replays a directory of images. Backbone of
  offline testing and macOS development.
- **`genicam.py`** — `HarvesterCamera`: the real driver (Harvester + GenTL `.cti`
  producer). Sets GenICam nodes (ExposureTime/Gain/AcquisitionFrameRate/ROI/
  TriggerMode/TriggerSource); fetches buffers → frames. Needs `.[camera]` + a
  producer (`cti_path` or `VIS_GENTL_CTI`). Runs on the Windows line PC.
- **`manager.py`** — `CameraManager`: register/lookup/open_all/close_all for the
  multiple cameras on a station (one acquisition process per camera at runtime).
- **`calibration.py`** — `Calibration`: pixel ↔ mm (uniform scale; richer
  distortion/perspective model can replace it behind the same interface).

## Why this shape

GenICam producers for macOS are poor (D-011), so the **real grab is built and
tested on Windows**, while the **abstraction + file/sim sources are fully testable
on macOS**. Same `CameraDevice` interface → no rework when the real camera lands.

## Status & what's next

Done: settings/trigger model, device interface + lifecycle, FileCamera, GenICam
driver (structure), manager, calibration. Verified: FileCamera replays through the
live pipeline; manager lifecycle; calibration math; GenICam fails with a clear
message when the driver/producer is absent.

Next camera-module work: live-mode latest-frame buffer for display; per-camera
acquisition processes wired to the worker pool; camera discovery/enumeration;
lighting/strobe control; focus-assist; on the Windows box — the real GenICam grab
+ encoder-to-reject latency spike (D-011).
