# Project state & handoff (read this first)

Industrial machine-vision inspection system for pharma packaging lines (verify
printed/coded text — B.No / MFG / EXP / MRP, GS1 DataMatrix/QR — and reject
non-conforming product). Python + PySide6 desktop HMI, SQLAlchemy/SQLite,
21 CFR Part 11 compliance. **~92 commits, ~290 tests passing, lint clean.**

> If you're a fresh Claude Code session on a new machine: the prior machine's
> chat memory does NOT transfer — this file + the `docs/` folder + the git
> history ARE the context. Skim `docs/`, run the test suite, then continue.

## What's built (all working + tested)
- **HMI**: live multi-camera view with pass/fail overlays + per-camera/lane
  results table; Teach screen (draw ROIs, OCR/OCV/code/measure tools, search
  regions, test, save, e-sign approve); Admin (users/products/batches/audit);
  Settings (exposure/gain/trigger); Stations; Fonts; Events; Comms; Challenge
  test; Audit review. Modern Qt theme.
- **Inspection**: code verify (GS1 parse + check digits + date/charset
  validation), OCR (PP-OCR/RapidOCR), OCV (trained per-character font library +
  auto-train from images), presence/measure/colour/template tools; inner+outer
  search regions; part location.
- **GMP/Part-11**: RBAC, PBKDF2, two-component e-signatures, hash-chained audit
  trail + **audit-trail review by exception** (release-gated), batch lifecycle +
  **reconciliation** (release-gated), **serial uniqueness/duplicate detection**,
  **challenge-test module** (line-start gate), **trusted-time/NTP** clock-tamper
  detection, OEE + downtime.
- **Integration**: VIS/1 TCP protocol + 24V line signals (docs/12); read-only
  REST API + multi-view web dashboard (docs/18); batch reports.
- **Cameras** (one `CameraDevice` interface): simulator; Hikrobot MVS
  (`camera/hikrobot.py`, Win/Linux); Aravis GigE (`camera/aravis_cam.py` +
  out-of-process worker `camera/aravis_proc.py` for macOS); GenTL/Harvester
  (`camera/genicam.py`).

## Run it
```bash
python -m venv .venv
.venv/bin/pip install -e .            # Windows: .venv\Scripts\pip install -e .
.venv/bin/vis-hmi                     # Windows: .venv\Scripts\vis-hmi
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q     # tests
```
Login `admin` / `admin123` (forces a password change on first login).

## Camera selection (env `VIS_CAMERA`)
`auto` (default) probes hikrobot → aravis → gentl → simulator.
- `VIS_CAMERA=hikrobot` + `VIS_MVS_PYTHON=<MVS python bindings dir>` — line PC.
- `VIS_CAMERA=gige` + `VIS_GENTL_CTI=<producer.cti>` — any GenTL producer
  (e.g. **Baumer**'s producer for the Baumer VCXG-24C we have).
- `VIS_CAMERA=aravis` — macOS / cross-platform open-source GigE (docs/19).
- `VIS_CAMERA=sim` — no camera.
Map ids: `VIS_HIK_MAP="cam1:0,cam2=<serial>"`.

## Current hardware status
- Camera in hand: **Baumer VCXG-24C** (color GigE, GS1-capable, Mono8/RGB8).
- On **macOS** it streamed real frames but the cheap **USB-to-GigE adapter** is
  flaky (GVCP control-channel timeouts). Use a Thunderbolt adapter, or — better —
  the **Windows line PC** where GigE + the vendor SDK are reliable.
- 42 real carton photos in `teachimage/` are a ready validation/golden set.

## Windows setup (see docs/20-windows-setup.md)
Install Python 3.11/3.12, clone/extract this repo, `pip install -e .`, then for
the Baumer use its **GenTL producer** with `VIS_CAMERA=gige VIS_GENTL_CTI=...`.

## Next steps (pick up here)
1. Get live frames on Windows (Baumer GenTL producer) and confirm in the HMI.
2. Teach the Sun Pharma carton recipe (B.No/MFG/EXP/MRP) — OCR per field +
   digits charset on dates; trained OCV font "Sun Pharma carton (TIJ)" exists.
3. Build a golden set with `vis-ocrbench` and tune reading.
