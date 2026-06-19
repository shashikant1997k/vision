#!/bin/bash
# Raise macOS UDP socket buffers for GigE Vision *continuous stream* mode.
# NOTE: the worker defaults to the reliable per-frame "oneshot" mode, which does
# NOT need this. Only run this if you switch to stream mode (acq_mode=stream).
# macOS hard-caps kern.ipc.maxsockbuf (often ~8 MB), so we raise what we can and
# never fail.  Run:  sudo bash scripts/mac_gige_tune.sh   (resets on reboot)
sysctl -w net.inet.udp.recvspace=6291456 2>/dev/null || true   # 6 MB UDP recv (under maxsockbuf)
sysctl -w kern.ipc.maxsockbuf=8388608 2>/dev/null || true       # keep at the macOS ceiling
echo "Current values:"
sysctl kern.ipc.maxsockbuf net.inet.udp.recvspace
