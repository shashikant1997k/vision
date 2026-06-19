# Developing with a real GigE camera on macOS

**Key fact:** Hikrobot's **MVS SDK is Windows/Linux only** — there is no macOS
build. On a Mac you acquire from the camera through **Aravis**, the open-source
GigE Vision / GenICam library, which works on Apple Silicon and talks to any
GigE-Vision-compliant camera (including Hikrobot). The Hikrobot MVS driver in
this app is for the **line PC** (Windows/Linux); the Aravis driver is for **Mac
development**. Both expose the identical interface, so your recipes/app are the
same on either.

---

## 1. Install Aravis + Python bindings

```bash
brew install aravis pygobject3 gobject-introspection
# point the app's venv at the system PyGObject (Aravis ships GI typelibs via brew)
.venv/bin/pip install pygobject
```

Verify Python can see Aravis:

```bash
.venv/bin/python -c "import gi; gi.require_version('Aravis','0.8'); from gi.repository import Aravis; print('Aravis', Aravis.get_major_version(), Aravis.get_minor_version())"
```

If that import fails, set the GI search path (brew prefix varies on Intel vs
Apple Silicon):

```bash
export GI_TYPELIB_PATH="$(brew --prefix)/lib/girepository-1.0"
export DYLD_LIBRARY_PATH="$(brew --prefix)/lib"
```

## 2. Network the camera (GigE basics — the part people miss)

A GigE camera is an Ethernet device; it must be on the **same subnet** as the
Mac NIC it's plugged into.

1. Connect the camera (PoE injector or its own power) to the Mac via Ethernet
   (a USB-C/Thunderbolt → Ethernet adapter is fine). Use a **Gigabit** link.
2. **System Settings → Network → that Ethernet adapter → Details → TCP/IP →
   Configure IPv4: Manually.** Give the Mac e.g. `192.168.1.10` / `255.255.255.0`.
   (Most Hikrobot cameras ship in DHCP/LLA; Aravis still finds them via GigE
   discovery even before they have a matching IP.)
3. Find the camera and (if needed) put it on your subnet:
   ```bash
   arv-tool-0.8                      # lists detected cameras + their IDs
   arv-tool-0.8 -n <camera-id> control GevPersistentIPAddress=192.168.1.20 \
       GevPersistentSubnetMask=255.255.255.0 GevPersistentIPConfiguration=Persistent
   ```
4. Raise the MTU to **9000 (jumbo frames)** on the Mac adapter if it supports it
   (System Settings → … → Hardware → MTU: Jumbo) — fewer dropped packets at
   speed. macOS GigE throughput is adapter-dependent; for high frame rates the
   Windows/Linux line PC is still the production target.

Quick grab test outside the app:
```bash
arv-tool-0.8                        # confirm the camera is listed
arv-viewer-0.8                      # live view (sanity check exposure/focus)
```

## 3. Run the app against the real camera

```bash
VIS_CAMERA=aravis .venv/bin/vis-hmi
```

- `VIS_CAMERA=aravis` forces the Aravis driver (otherwise the app auto-detects:
  Hikrobot SDK → Aravis → GenTL → simulator).
- Multiple cameras: `VIS_HIK_MAP="cam1:0,cam2:1"` (enumeration index) or
  `VIS_HIK_MAP="cam1=<serial>"` — the same mapping drives the Aravis driver.
- In the app: **Settings…** sets exposure / gain / frame-rate / trigger; for
  coding lines use a **hardware trigger** (Trigger → hardware, on `Line0`) with
  the part sensor + strobe.
- Set the camera **PixelFormat to Mono8 or RGB8** (via `arv-tool` or the MVS
  client on a Windows box) — the driver decodes those; it errors clearly on
  other formats.

## 4. Recommended workflow

- **Mac (this machine):** develop, teach recipes, run the test suite, and grab
  live frames via Aravis for teaching/golden sets.
- **Line PC (Windows/Linux):** deploy with the Hikrobot MVS SDK
  (`VIS_CAMERA=hikrobot`, set `VIS_MVS_PYTHON`) for production-grade throughput,
  hardware trigger and 24 V reject I/O.

Because both drivers implement the same `CameraDevice` interface, a recipe
taught on the Mac runs unchanged on the line PC.

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `arv-tool` lists nothing | Check cable/PoE; disable the Mac firewall for discovery; confirm the adapter is up; try `arv-tool-0.8 --debug all` |
| Camera seen but no frames | Subnet mismatch — give the Mac a static IP in the camera's range; lower packet size if jumbo frames aren't supported |
| `Aravis not found` in the app | Re-check step 1 (GI_TYPELIB_PATH / DYLD_LIBRARY_PATH) |
| Unsupported pixel format error | Set PixelFormat = Mono8 or RGB8 |
| Low/unstable frame rate | Use a wired Gigabit link, jumbo frames, lower resolution/ROI; for production use the line PC |
