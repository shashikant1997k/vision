"""Machine fingerprint for node-locked licenses.

A stable, non-secret identifier for one inspection station, derived from
hardware/OS identifiers that survive reboots and software updates but change
when the license is copied to a different PC:

- Windows: MachineGuid (registry) — the standard Windows install identity
- Linux:   /etc/machine-id  (or /var/lib/dbus/machine-id)
- macOS:   IOPlatformUUID   (dev machines)
- fallback: the primary MAC address

The raw value is never shown or stored — we publish only its SHA-256, so a
fingerprint in a license file leaks nothing about the customer's hardware.

Deliberately NOT fuzzy-matched: an exact fingerprint plus an explicit activation
record is what auditors (and support engineers) can reason about. When a station
is replaced, support issues a new license — a normal, logged event.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid
from pathlib import Path

_SALT = b"vis-machine-v1"


def _windows_machine_guid() -> str | None:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        return None


def _linux_machine_id() -> str | None:
    for p in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            if p.is_file():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def _macos_platform_uuid() -> str | None:
    try:
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5,
        ).stdout
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return None


def _mac_address() -> str | None:
    node = uuid.getnode()
    # getnode() invents a random multicast address when it can't read a real NIC
    return None if (node >> 40) & 0x1 else f"{node:012x}"


def raw_machine_id() -> str:
    """Platform identifier before hashing (internal; may be empty)."""
    system = platform.system()
    value = (
        _windows_machine_guid() if system == "Windows"
        else _macos_platform_uuid() if system == "Darwin"
        else _linux_machine_id()
    )
    return value or _mac_address() or ""


def machine_fingerprint() -> str:
    """Stable SHA-256 fingerprint of this station (hex). Safe to print/ship."""
    raw = raw_machine_id()
    if not raw:
        # No stable identifier — hostname keeps node-locking meaningful rather
        # than silently binding every machine to the same value.
        raw = f"hostname:{platform.node()}"
    return hashlib.sha256(_SALT + raw.encode("utf-8")).hexdigest()


def fingerprint_report() -> dict:
    """What support asks the customer to read out when issuing a license."""
    return {
        "fingerprint": machine_fingerprint(),
        "hostname": platform.node(),
        "system": f"{platform.system()} {platform.release()}",
    }
