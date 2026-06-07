# Packaging

Build a distributable Qt HMI for the Windows line PC.

## Prerequisites

- Build on a **Windows** machine (PyInstaller is not a cross-compiler).
- A project virtualenv with the app and licensed extras installed:
  `pip install -e ".[codes,ocr,camera,io,hmi,postgres]"`
- `pip install pyinstaller`

## Build

```bat
pyinstaller packaging\vis-hmi.spec
```

Output: `dist\vis-hmi\vis-hmi.exe` (one-folder bundle). Smoke-test it on a clean
machine without Python installed.

## Then make an installer (MSI)

Wrap `dist\vis-hmi\` with an installer that:

1. Installs the bundle under `C:\Program Files\VisionInspection\`.
2. Creates a Start-menu / desktop shortcut to `vis-hmi.exe`.
3. Sets `DATABASE_URL` and `VIS_GENTL_CTI` (system env vars) or writes a config file.
4. Records the **installed version + git commit** (for IQ).

Recommended tooling: **WiX Toolset** or **Inno Setup**.

## Verify (post-build)

- Launch on a clean Windows box → login window appears.
- Confirm OCR (rapidocr models bundled), code decode (zxingcpp), and camera
  enumeration (with the GenTL producer installed) work.
- Run the IQ smoke checks ([validation/02-iq.md](../docs/validation/02-iq.md) §E).

## Caveats

- **GenTL producer (.cti)** is licensed/installed separately (not bundled); the
  app finds it via `VIS_GENTL_CTI`.
- **PostgreSQL** is installed separately (or pointed at a central server).
- Verify the bundled ONNX OCR models load on the target — they are large data
  files collected by the spec; missing them breaks the OCR tool.
