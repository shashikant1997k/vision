#!/usr/bin/env bash
# Provision an Ubuntu (ARM or x86) VM/PC to run the vision app + ocr-trainer +
# Aravis, with GigE socket tuning. Run INSIDE Ubuntu after the OS is installed:
#
#   bash provision_linux.sh                 # apps live under ~/camera (shared folder or clones)
#   BASE=/media/psf/Home/Personal/camera bash provision_linux.sh   # VMware shared folder
#
# Baumer GAPI SDK: download the Linux ARM build from baumer.com, then:
#   bash provision_linux.sh --baumer ~/Downloads/Baumer_GAPI_SDK_*_lin_aarch64.tar.gz
#
# Idempotent — safe to re-run.
set -euo pipefail

BASE="${BASE:-$HOME/camera}"
BAUMER_PKG=""
[ "${1:-}" = "--baumer" ] && BAUMER_PKG="${2:-}"

echo "==> System packages"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip python3-dev build-essential git curl \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
  libxcb-cursor0 libxkbcommon0 libxcb-xinerama0 libegl1 libdbus-1-3 \
  aravis-tools gir1.2-aravis-0.8 python3-gi python3-gi-cairo

echo "==> GigE socket-buffer tuning (the knob macOS hard-caps)"
sudo tee /etc/sysctl.d/99-gige.conf >/dev/null <<'SYS'
net.core.rmem_max = 67108864
net.core.rmem_default = 67108864
net.core.wmem_max = 33554432
SYS
sudo sysctl --system >/dev/null
echo "   rmem_max=$(sysctl -n net.core.rmem_max)"

mkdir -p "$BASE"
cd "$BASE"

# --- vision app ---
if [ ! -d "$BASE/vision/.git" ] && [ ! -d "$BASE/vision/src" ]; then
  echo "==> Cloning vision"
  git clone https://github.com/shashikant1997k/vision.git vision || \
    git clone git@github.com:shashikant1997k/vision.git vision
fi
echo "==> vision venv + install"
cd "$BASE/vision"
python3 -m venv .venv
./.venv/bin/pip install -U pip wheel
./.venv/bin/pip install -e .
./.venv/bin/pip install -e ".[ocr]" || echo "   (ocr extra optional — skipped if it failed)"
echo "   vision ready: cd $BASE/vision && .venv/bin/vis-hmi"

# --- ocr-trainer ---
if [ -d "$BASE/ocr-trainer" ]; then
  echo "==> ocr-trainer venv + install (CPU; train on RunPod)"
  cd "$BASE/ocr-trainer"
  python3 -m venv .venv
  ./.venv/bin/pip install -U pip wheel
  ./.venv/bin/pip install -r requirements.txt
  echo "   ocr-trainer ready (data gen/eval here; training on RunPod GPU)"
else
  echo "==> ocr-trainer not found at $BASE/ocr-trainer — copy it in (shared folder"
  echo "    or 'git clone') and re-run, or run its requirements manually."
fi

# --- Baumer GAPI SDK (optional, vendor GenTL producer) ---
if [ -n "$BAUMER_PKG" ] && [ -f "$BAUMER_PKG" ]; then
  echo "==> Installing Baumer GAPI SDK from $BAUMER_PKG"
  mkdir -p "$HOME/baumer" && tar -xf "$BAUMER_PKG" -C "$HOME/baumer"
  CTI=$(find "$HOME/baumer" -name "*.cti" 2>/dev/null | head -1)
  if [ -n "$CTI" ]; then
    echo "   GenTL producer: $CTI"
    echo "   export GENICAM_GENTL64_PATH=$(dirname "$CTI")"
    echo "   run vendor path:  VIS_CAMERA=gige VIS_GENTL_CTI=$CTI .venv/bin/vis-hmi"
  fi
  # Baumer ships a setup script too; run it if present
  SETUP=$(find "$HOME/baumer" -name "install*.sh" 2>/dev/null | head -1)
  [ -n "$SETUP" ] && echo "   (vendor installer found: bash $SETUP  — run for udev/driver bits)"
else
  echo "==> Baumer SDK not provided (optional). Aravis already works:"
  echo "    VIS_CAMERA=aravis .venv/bin/vis-hmi"
fi

echo ""
echo "==> Done. Camera quickstart:"
echo "    arv-tool-0.8                 # confirm the camera is seen"
echo "    cd $BASE/vision && VIS_CAMERA=aravis .venv/bin/vis-hmi"
