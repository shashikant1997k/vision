# Building and installing on a client PC

You noticed that most industrial vendors just put a folder on the machine and
run it. That is right, and it is what we do too — the difference is **what goes
in the folder**.

Copying the source tree would mean installing Python on every line PC, and it
would hand the customer our source and our trained models. Instead we build a
**self-contained folder**: one `.exe` plus every DLL and data file it needs. You
copy it and run it. No Python, no pip, no internet on the line PC.

---

## 1. Build (on a Windows machine, once per release)

```bat
python -m venv .venv
.venv\Scripts\pip install -e ".[engine,ocr,camera]"
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python packaging\build_windows.py
```

That produces **`dist\vis-hmi\`** — that whole folder is the product.

The build script does not just build; it **starts the frozen app and asks it
what it can actually do**, then fails if anything is missing. This matters more
than it sounds: our inspection tools and readers register themselves *when their
module is imported*, and PyInstaller cannot see that. Drop one and the build
still succeeds — the failure appears when an operator runs that inspection on a
live batch. The verification turns that into a build error instead.

You can re-check any existing build:

```bat
.venv\Scripts\python packaging\build_windows.py --verify-only dist\vis-hmi
```

**Build on the OS you ship to.** A PyInstaller build is not cross-platform: a
Windows build must be produced on Windows.

---

## 2. What to put on the line PC

Copy `dist\vis-hmi\` to the machine (e.g. `C:\ControlPrint\vis-hmi\`) and add
four things beside `vis-hmi.exe`:

```
C:\ControlPrint\vis-hmi\
  vis-hmi.exe            the application
  _internal\             its libraries (do not touch)
  model\                 this customer's .onnx + .charset.txt + .onnx.sha256
  vision.lic             the licence issued for THIS station
  config.json            site settings — camera, I/O, image archive
```

They are separate on purpose:

- **Models** are per customer, and `vis-license package` encrypts them to that
  customer's licence — so they can be replaced or updated without a rebuild.
- **The licence** is per station (node-locked to its fingerprint).
- **The config** is what a plant engineer edits; nothing in it needs a new build.
- **The GenTL producer** (`.cti`) is vendor-licensed and installed with the
  camera SDK — Baumer GAPI, Hikrobot MVS or Basler pylon — then pointed at with
  `camera.gentl_cti`.

### Issuing the licence

On the line PC:

```bat
vis-hmi.exe --selftest
```

Read the `machine_fingerprint` from the output and, back at the office:

```bat
vis-license issue --customer "Plant X - Line 3" --packs pharma-ocv,codes ^
                  --machine <fingerprint> --expires 2027-08-06 --out PlantX-L3.lic
vis-license package --license CPL-2026-0007 --models model\*.onnx --out dist\model
```

Copy `PlantX-L3.lic` to the station as `vision.lic`, and the encrypted `model\`
folder beside the exe.

### A minimal `config.json`

```json
{
  "station": "Line 3",
  "camera": {
    "source": "gige",
    "gentl_cti": "C:/Program Files/Baumer/Baumer GAPI SDK/bin/bgapi2_gige.cti",
    "device_id": "700011045955",
    "packet_size": 1500
  },
  "io": { "backend": "modbus", "host": "192.168.0.50", "port": 502 },
  "images": { "policy": "fails", "dir": "D:/vision-images" },
  "line": { "alarm_consecutive_rejects": 5 }
}
```

---

## 3. Verify the installation (and keep the evidence)

```bat
vis-hmi.exe --selftest > IQ-station3.json
```

That single command records the version, the tools and readers present, which
model files resolved, the machine fingerprint and the licence state. It is
exactly what an IQ needs as evidence, and it is the first thing to run when a
site reports odd behaviour.

Then launch `vis-hmi.exe`, log in, and confirm the camera streams before
teaching anything.

For a validated installation, also checksum the folder so you can prove later
that nothing changed:

```bat
certutil -hashfile vis-hmi.exe SHA256
```

---

## 4. Updating a site

Replace the folder, keep `model\`, `vision.lic` and `config.json`. Re-run
`--selftest` and compare it with the record from the last install — that diff is
your change-control evidence.

---

## 5. Honest limits of this approach

**A PyInstaller build is not protection.** The bundle can be unpacked and the
bytecode decompiled with public tools. What it gives you is convenience: one
folder, no Python on the line PC. The things that actually protect the product
are the signed licence, the per-customer encrypted models, and — before you sell
this — **compiling with Nuitka Commercial** so the code is native rather than
bytecode. Treat the current build as good enough for pilots and internal lines,
not as the shipping configuration for a paid customer.

**Startup takes a few seconds** on first launch while Windows loads the DLLs.
That is normal for a onedir build and much faster than a onefile build, which
unpacks itself to a temp folder every single time — avoid onefile for a line PC.
