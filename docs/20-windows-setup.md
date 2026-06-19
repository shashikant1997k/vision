# Running on a Windows laptop / line PC

Windows is the reliable home for the camera (native vendor SDKs + stable GigE).

## 1. Get the code onto Windows
Pick one:
- **USB / file copy (offline):** copy the `camera.bundle` file (a single-file git
  archive made on the Mac with `git bundle create camera.bundle --all`), then:
  ```powershell
  git clone camera.bundle camera
  cd camera
  ```
- **GitHub (for ongoing sync):** create a private repo, then on the Mac
  `git remote add origin <url>; git push -u origin master`, and on Windows
  `git clone <url> camera`.

## 2. Python environment
Install **Python 3.11 or 3.12** (python.org; tick "Add to PATH"). Then:
```powershell
cd camera
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\pip install -e ".[ocr]"     # optional: OCR engine (rapidocr)
```
Verify:
```powershell
set QT_QPA_PLATFORM=offscreen
.venv\Scripts\python -m pytest -q
.venv\Scripts\vis-hmi
```

## 3. Connect the Baumer VCXG-24C (recommended: GenTL producer)
The cleanest vendor-supported path on Windows uses Baumer's **GenTL producer**
with the app's GenTL/Harvester driver:

1. Install **Baumer GAPI SDK / neoAPI** (free from baumer.com → Downloads). It
   ships a GenTL **producer `.cti`** file, typically under
   `C:\Program Files\Baumer\...\bin\bgapi2_gige.cti` (name varies).
2. Install the **harvesters** Python package into the venv:
   ```powershell
   .venv\Scripts\pip install harvesters
   ```
3. Network the camera: a wired Gigabit NIC; set it to a static IP on the
   camera's subnet (the camera is at `192.168.60.151`, so the PC e.g.
   `192.168.60.10 / 255.255.255.0`). Use Baumer's IP-config tool or
   `arv-tool`/the camera webpage if needed.
4. Run the app pointed at the producer:
   ```powershell
   set VIS_CAMERA=gige
   set VIS_GENTL_CTI=C:\Program Files\Baumer\...\bgapi2_gige.cti
   .venv\Scripts\vis-hmi
   ```

Alternatives:
- **Hikrobot MVS** (if you also use Hikrobot cameras): install MVS, set
  `VIS_MVS_PYTHON` to its Python bindings dir, `set VIS_CAMERA=hikrobot`.
- **Aravis for Windows** also works (`VIS_CAMERA=aravis`) but the GenTL producer
  is the smoother Windows route for the Baumer.

## 4. Camera settings in the app
- **Settings…**: exposure / gain / frame rate / trigger. For a coding line use a
  **hardware trigger** (Trigger → hardware, `Line0`) with the part sensor +
  strobe.
- Set **PixelFormat = Mono8** (best for code/text) or RGB8.
- Continuous streaming is reliable on Windows (no socket-buffer workaround
  needed, unlike macOS).

## 5. Continuing the assistant on Windows
A fresh Claude Code session here won't have the Mac session's memory — point it
at this repo: it reads `PROJECT_STATE.md` + `docs/`. Suggested opener:
> "Read PROJECT_STATE.md and docs/, run the tests, then help me get live frames
>  from the Baumer VCXG-24C via the Baumer GenTL producer and teach the Sun
>  Pharma carton recipe."
