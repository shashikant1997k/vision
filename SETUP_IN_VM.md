# Runbook — set up vision + ocr-trainer + Baumer camera in the Ubuntu ARM VM

**Audience: Claude Code running *inside* the Ubuntu VM.** Execute these steps in
order. The user drives the two GUI-only steps (marked **[USER]**); everything
else you can run in the terminal. Report results after each numbered section.

Context: this is an Ubuntu 24.04 **ARM64** guest in VMware Fusion on an Apple
Silicon Mac. The macOS host could not hold a stable GigE link to the Baumer
camera (control channel / packet loss). The VM fixes this by owning the USB
Ethernet NIC directly and raising the socket buffers macOS capped.

---

## 1. Create the workspace and pull both repos
```bash
mkdir -p ~/camera && cd ~/camera
git clone https://github.com/shashikant1997k/vision.git         # public
git clone git@github.com:shashikant1997k/ocr-trainer.git        # private (SSH key added)
ls ~/camera            # expect: vision  ocr-trainer
```

## 2. Confirm architecture (decides the Baumer SDK variant)
```bash
uname -m
```
- `aarch64` → download **Baumer GAPI SDK for Linux ARM** (this is the expected case).
- `x86_64`  → download **Baumer GAPI SDK for Linux** instead.

## 3. Provision everything (deps + Aravis + both venvs + GigE socket tuning)
```bash
bash ~/camera/vision/scripts/provision_linux.sh
```
`BASE` defaults to `~/camera`, so it sets up **both** `vision` and `ocr-trainer`
venvs, installs Aravis (`aravis-tools`, `gir1.2-aravis-0.8`, `python3-gi`), and
writes `/etc/sysctl.d/99-gige.conf` (`net.core.rmem_max=64MB`). Idempotent.

Sanity check after it finishes:
```bash
arv-tool-0.8 --version
~/camera/vision/.venv/bin/python -c "import vis; print('vis OK')"
sysctl net.core.rmem_max        # expect 67108864
```

## 4. Baumer GAPI SDK (Linux ARM / aarch64) — optional vendor producer
Aravis alone already talks to the camera; the Baumer GenTL producer is only
needed for the `VIS_CAMERA=gige` vendor path.

**[USER]** Download the **Linux ARM (aarch64)** build from
<https://www.baumer.com/in/en/product-overview/industrial-cameras-image-processing/software/baumer-gapi-sdk/c/14174>
(free, requires registration) into `~/Downloads/`. Then:
```bash
bash ~/camera/vision/scripts/provision_linux.sh \
     --baumer ~/Downloads/Baumer_GAPI_SDK_*_lin_aarch64.tar.gz
```
Note the printed GenTL `.cti` path (e.g. `.../bgapi2_gige.cti`) — you'll pass it
as `VIS_GENTL_CTI` in step 6.

## 5. Give the VM the camera
**[USER]** Two GUI actions on the Mac side:
1. Plug the **USB Ethernet adapter** into the Mac.
2. Fusion menu → **Virtual Machine → USB → connect "USB 10/100/1000 LAN"** to
   the VM (so the *guest* owns the NIC, not macOS).

Then, in the VM, put that NIC on the camera's subnet:
```bash
ip -br link                      # find the new wired NIC name (e.g. ens160 / enp2s0)
NIC=ens160                       # <-- set to the name you just saw
sudo nmcli con add type ethernet ifname "$NIC" con-name cam ipv4.method manual \
     ipv4.addresses 192.168.60.10/24
sudo nmcli con up cam
ping -c3 192.168.60.151          # camera should reply
```

## 6. Verify and run the app
```bash
arv-tool-0.8                     # should list: Baumer-VCXG-24C-... (192.168.60.151)
cd ~/camera/vision

# Simplest, vendor-free (Aravis):
VIS_CAMERA=aravis .venv/bin/vis-hmi

# Or the Baumer vendor GenTL producer (from step 4):
# VIS_CAMERA=gige VIS_GENTL_CTI=<path to bgapi2_gige.cti> .venv/bin/vis-hmi
```
On Linux the continuous stream should be stable now (direct NIC + raised socket
buffers) — no more disconnects/packet-loss like on macOS.

## 7. OCR is already trained — enable the reader
The trained models ship in the repo at `~/camera/ocr-trainer/model/`:
`ocrab_svtr256.onnx` (recommended recogniser, 93.5% char / 63.5% field on real
blisters) + `textline_det.onnx` (line detector) + sidecar charsets. The vision
app auto-discovers this path (`~/camera/ocr-trainer/model`) — no config needed.
Turn the reader on when launching the app:
```bash
cd ~/camera/vision
VIS_TEXT_READER=vis_ocr VIS_CAMERA=aravis .venv/bin/vis-hmi
```
Verify the models are present and load:
```bash
ls -lh ~/camera/ocr-trainer/model/*.onnx     # svtr256 (~28M) + textline_det (~10M)
~/camera/vision/.venv/bin/python -c "from vis.tools.vis_ocr_reader import _find_model; print(_find_model())"
```
(fp32 svtr256 is used, not INT8 — INT8 is slower on ARM per `model/README.md`.)

## 8. ocr-trainer (retrain / eval; training on RunPod)
The provisioner made its venv. Data generation and ONNX evaluation run here; GPU
training runs on RunPod (no torch in this venv). Full plan: `ocr-trainer/START_HERE.md`.
```bash
cd ~/camera/ocr-trainer
./.venv/bin/python -c "import ocrtrainer.synth as s; print('synth OK')"
```

---

## Troubleshooting
- **`arv-tool-0.8` shows nothing:** the USB NIC isn't passed through (redo step 5.1)
  or the IP isn't on `192.168.60.x` (redo step 5). `ping 192.168.60.151` must work first.
- **Aravis binding not found:** the app never imports Aravis into its own venv —
  it spawns an out-of-process worker (`scripts/aravis_worker.py`) under the system
  `/usr/bin/python3`, which has the apt `python3-gi` + `gir1.2-aravis-0.8` bindings.
  If the worker can't find an Aravis-capable interpreter, set
  `VIS_ARAVIS_PYTHON=/usr/bin/python3` before launching `vis-hmi`, and confirm
  `python3 -c "import gi; gi.require_version('Aravis','0.8'); from gi.repository import Aravis"`
  runs cleanly with the system python3.
- **Stream still drops frames:** confirm `sysctl net.core.rmem_max` is 67108864;
  re-run step 3 if not.
