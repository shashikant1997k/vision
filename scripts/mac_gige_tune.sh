#!/bin/bash
# Raise macOS kernel socket buffers so GigE Vision continuous streaming doesn't
# overflow (the default 8 MB maxsockbuf drops ~100% of a continuous feed). Run
# once per boot:  sudo bash scripts/mac_gige_tune.sh
# (these are runtime sysctls; they reset on reboot — re-run after a restart.)
set -e
sysctl -w kern.ipc.maxsockbuf=33554432      # 32 MB socket buffer ceiling
sysctl -w net.inet.udp.recvspace=8388608     # 8 MB default UDP receive buffer
echo "Done. Current values:"
sysctl kern.ipc.maxsockbuf net.inet.udp.recvspace
