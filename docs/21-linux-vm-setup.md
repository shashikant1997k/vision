# Running the camera on a Linux VM on your Mac (MacBook Air M3, 16 GB)

The Baumer camera + adapter work perfectly on Windows/Linux but macOS limits
continuous GigE streaming (socket-buffer cap). An **Ubuntu ARM VM** runs the app
+ Baumer **Linux ARM** SDK *natively* (no emulation), and Linux lets us raise the
socket buffer macOS blocked. USB-passthrough the Ethernet adapter and the Linux
guest owns the NIC directly.

## VM resource allocation (your M3 / 16 GB — "maximum but safe")
Leave headroom for macOS or the whole machine swaps and stutters.
- **CPU:** 6 of 8 cores  *(don't give all 8)*
- **RAM:** **8 GB**  *(max safe on a 16 GB Mac; 10 GB only if you quit everything else on macOS)*
- **Disk:** 60 GB virtual disk, **thin-provisioned** (actually uses ~20 GB)
- **Graphics:** enable "Accelerate 3D Graphics"

## 1. Install the VM + Ubuntu (manual — ~30–40 min)
1. Install **VMware Fusion** (free for personal use, from Broadcom) — or UTM.
2. Download **Ubuntu 24.04 LTS Desktop for ARM64** (ubuntu.com/download/server/arm
   → Desktop ARM image), the `.iso`.
3. New VM → install from the ISO → set CPU/RAM/disk per above → finish the Ubuntu
   installer (create your user, let it reboot).
4. In Ubuntu: open Terminal, `sudo apt update`.

## 2. Give the guest the camera (USB passthrough)
- Plug the USB Ethernet adapter into the Mac.
- VMware Fusion menu → **Virtual Machine → USB & Bluetooth → connect the
  "USB 10/100/1000 LAN" to Linux** (so the *guest* owns it, not macOS).
- In Ubuntu, set a static IP on that NIC in the camera's subnet:
  Settings → Network → wired → IPv4 → Manual → `192.168.60.10 / 255.255.255.0`.
- `ping 192.168.60.151` should reply.

## 3. Get both apps into the VM
Easiest: **VMware shared folder** — share your Mac `~/Personal/camera` folder into
the VM (Virtual Machine → Sharing). It appears at `/media/psf/Home/Personal/camera`
(VMware) and both `vision/` and `ocr-trainer/` are right there.
Or `git clone https://github.com/shashikant1997k/vision.git` (and copy `ocr-trainer`).

## 4. Download the Baumer GAPI SDK (manual)
From baumer.com → Baumer GAPI SDK → **Linux ARM** build (free, registration).
Save the `.tar.gz` into the VM (e.g. `~/Downloads/`).

## 5. Provision everything (one command)
```bash
# inside Ubuntu, from where you put the repo:
BASE=/media/psf/Home/Personal/camera \
  bash vision/scripts/provision_linux.sh --baumer ~/Downloads/Baumer_GAPI_SDK_*aarch64.tar.gz
```
This installs system deps + Aravis, sets up **vision** and **ocr-trainer** venvs,
raises the GigE socket buffers (`net.core.rmem_max=64MB`), and unpacks the Baumer
SDK / finds its GenTL `.cti`.

## 6. Run
```bash
arv-tool-0.8                                            # confirm camera seen
cd <base>/vision
VIS_CAMERA=aravis .venv/bin/vis-hmi                     # simplest, vendor-free
# or the Baumer vendor producer:
VIS_CAMERA=gige VIS_GENTL_CTI=<path to bgapi2_gige.cti> .venv/bin/vis-hmi
```
Continuous streaming should now be stable (raised socket buffer + direct NIC).

## Performance (what to expect)
Apple-Silicon ARM virtualization is near-native — the app + ONNX inference run at
near bare-metal CPU speed; ~60–120 ms per product (1 code + 6 lines). No GPU in
the guest (fine — inference is CPU; training stays on RunPod). VM GUI is slightly
less snappy than native but fine for an inspection HMI. For sustained max
production throughput, a dedicated bare-metal PC is still preferred.

## ocr-trainer note
You only generate data / evaluate / export here. **Training runs on RunPod GPU**
(see `ocr-trainer/START_HERE.md`); torch is not installed by the provisioner.
