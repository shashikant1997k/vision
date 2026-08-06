# Camera setup

The app talks to a camera through one of four backends, chosen with
`VIS_CAMERA`. Pick the first one that applies to your machine.

| `VIS_CAMERA` | Backend | Use it for |
|---|---|---|
| `file` | replays saved images | **development** — the full pipeline with no camera |
| `aravis` | Aravis (open-source GigE Vision) | Linux line PC / dev machine |
| `gige` | GenTL producer (`VIS_GENTL_CTI`) | any GigE Vision camera with a vendor `.cti` |
| `hikrobot` | Hikrobot MVS SDK | Hikrobot cameras on a Windows/Linux line PC |
| *(unset)* | auto-detect, else simulator | first run |

## Development without a camera (recommended)

Everything except live capture — OCR/OCV, recipes, batches, reports, the whole
HMI — runs against saved images at full speed:

```bash
VIS_CAMERA=file VIS_TEXT_READER=vis_ocr .venv/bin/vis-hmi
```

`VIS_FILE_DIR` points it at any folder of images (default: `teachimage/`).
This is the intended way to develop; it needs no hardware and no VM.

## Platform reality

**Windows and Linux run the camera. macOS does not.**

This was established the hard way, so it is recorded here to save the next
person the same week:

| Stack tried on macOS | Result |
|---|---|
| Aravis | control channel wedges — `read_memory` timeouts |
| Hikrobot MVS.app (vendor GUI) | connects, then packet loss and disconnects |
| Hikrobot MVS SDK under Rosetta | one frame, then "no data" timeouts; wedges the camera |

The hardware is fine — the same camera and adapter stream perfectly on Windows.
The failure is in how macOS handles the GigE Vision control channel and its
socket-buffer ceiling. **Do not spend time on live camera under macOS.**
Develop with `VIS_CAMERA=file` on any machine, and use a Windows or Linux PC for
live capture and validation.

## GigE Vision networking (Windows/Linux)

1. Give the PC's NIC a static address on the camera's subnet — camera
   `192.168.60.151` → NIC `192.168.60.10`, mask `255.255.255.0`.
2. Disable other interfaces (Wi-Fi especially) while setting up. With two
   interfaces up, discovery can latch onto the wrong one and report the camera
   as unreachable even though it responds to `ping`.
3. `ping 192.168.60.151` must reply before any software will work.
4. Confirm discovery: `arv-tool-0.8` (Aravis) or the vendor's viewer.

**Packet loss / disconnects** on a working link are almost always one of:
- **Packet size** — a USB-Ethernet adapter usually cannot pass jumbo frames.
  Set `GevSCPSPacketSize` to `1500`.
- **Data rate** — cap `AcquisitionFrameRate`, or raise `GevSCPD` (inter-packet
  delay) so the host can keep up.
- **Socket buffers (Linux)** — `net.core.rmem_max = 67108864` in
  `/etc/sysctl.d/`, then `sudo sysctl --system`.

## Aravis (Linux)

```bash
sudo apt install -y aravis-tools gir1.2-aravis-0.8 python3-gi
arv-tool-0.8                                  # camera should be listed
VIS_CAMERA=aravis .venv/bin/vis-hmi
```

The app never imports the Aravis binding into its own process — it runs
`scripts/aravis_worker.py` under the system `python3` (which has the apt
`python3-gi` bindings) and reads framed images from its stdout. If the worker
cannot find a suitable interpreter, set `VIS_ARAVIS_PYTHON=/usr/bin/python3`.

## Vendor GenTL producer

Any GigE Vision camera with a vendor `.cti` (Baumer GAPI, Hikrobot MVS,
Basler pylon):

```bash
VIS_CAMERA=gige VIS_GENTL_CTI=/path/to/producer.cti .venv/bin/vis-hmi
```

The chosen camera and producer are remembered, so later launches need only
`vis-hmi`.

## Diagnostics

| Script | What it answers |
|---|---|
| `scripts/app_cam_check.py` | does the app see a camera at all? |
| `scripts/gentl_probe.py` | which GenTL producers/devices are visible |
| `scripts/gentl_grab.py` | can we pull one frame through GenTL? |
| `scripts/aravis_snapshot.py` | can we pull one frame through Aravis? |
| `scripts/live_focus.py` | live focus/sharpness meter while adjusting the lens |

**If the camera stops responding** after repeated connection attempts, its
control channel is wedged: power-cycle the camera (remove power ~10 s). Rapid
open/abort cycles cause this — open once, use it, close it.
