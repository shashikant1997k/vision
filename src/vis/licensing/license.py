"""Signed license files — capability entitlement for the vision platform.

Commercial model (mirrors HALCON/MERLIC/Aurora): ONE binary, features unlocked
by the content of a signed license. A license grants **capability packs**
(``pharma-ocv``, ``codes``, ``fill-level``, …); the tool registry lists only the
packs a site paid for, so new business is a new pack, not a new build.

A license is a JSON document plus a detached **Ed25519 signature** produced by
the vendor's private key (which never ships). The app holds only the public key,
so a license cannot be forged or edited — changing one byte invalidates it.

    {
      "license_id": "CPL-2026-0007",
      "customer": "Sun Pharma — Halol Line 3",
      "packs": ["pharma-ocv", "codes"],
      "machines": ["<fingerprint>"],      # [] = not node-locked
      "seats": 1,
      "issued": "2026-08-06",
      "expires": "2027-08-06",            # null = perpetual
      "grace_days": 14
    }

Node-locking binds a license to a machine fingerprint (see ``fingerprint.py``).
Air-gapped pharma lines are the norm, so verification is fully offline: no
server, no phone-home. ``expires`` supports subscription/AMC terms; perpetual
licenses simply omit it.

Enforcement points (deliberately more than one, per commercial practice):
app start, batch start, and tool registration. Every decision is logged so the
21 CFR Part 11 audit trail shows which license authorised production.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# Vendor's Ed25519 public key (base64, 32 bytes). Replace at build time with the
# real product key; the matching private key stays in the vendor's signing vault
# and NEVER ships. VIS_LICENSE_PUBKEY overrides for testing/self-hosted builds.
VENDOR_PUBLIC_KEY_B64 = ""

LICENSE_ENV = "VIS_LICENSE"            # explicit path to a .lic file
_DEFAULT_NAMES = ("vision.lic", "license.lic")


class LicenseError(RuntimeError):
    """License missing, malformed, forged, expired, or wrong machine."""


@dataclass(frozen=True)
class License:
    license_id: str
    customer: str
    packs: frozenset[str]
    machines: tuple[str, ...] = ()
    seats: int = 1
    issued: str = ""
    expires: str | None = None
    grace_days: int = 0
    path: Path | None = None
    raw: dict = field(default_factory=dict, repr=False)

    # ---- entitlement ----------------------------------------------------
    def has_pack(self, pack: str) -> bool:
        return pack in self.packs

    @property
    def expiry_date(self) -> date | None:
        return date.fromisoformat(self.expires) if self.expires else None

    def days_remaining(self, today: date | None = None) -> int | None:
        """Days until expiry (negative = in grace/expired); None if perpetual."""
        exp = self.expiry_date
        if exp is None:
            return None
        return (exp - (today or date.today())).days

    def check_valid(self, today: date | None = None, machine: str | None = None) -> None:
        """Raise LicenseError unless this license authorises production now/here."""
        today = today or date.today()
        exp = self.expiry_date
        if exp is not None:
            hard_stop = exp + timedelta(days=self.grace_days)
            if today > hard_stop:
                raise LicenseError(
                    f"license {self.license_id} expired on {exp.isoformat()} "
                    f"(grace {self.grace_days}d ended {hard_stop.isoformat()}). "
                    "Renew the AMC/subscription to resume production."
                )
        if self.machines:
            if machine is None:
                from .fingerprint import machine_fingerprint

                machine = machine_fingerprint()
            if machine not in self.machines:
                raise LicenseError(
                    f"license {self.license_id} is node-locked to another machine "
                    f"(this machine: {machine[:16]}…). Request a license for this "
                    "station or move the dongle/license file."
                )

    def audit_summary(self) -> dict:
        """Compact, log-safe description for the Part 11 audit trail."""
        return {
            "license_id": self.license_id,
            "customer": self.customer,
            "packs": sorted(self.packs),
            "expires": self.expires,
            "days_remaining": self.days_remaining(),
            "node_locked": bool(self.machines),
        }


# ---- signing / verification ---------------------------------------------
def _canonical(payload: dict) -> bytes:
    """Byte-exact form that gets signed (stable key order, no whitespace drift)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _public_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    raw = os.environ.get("VIS_LICENSE_PUBKEY", "") or VENDOR_PUBLIC_KEY_B64
    if not raw:
        raise LicenseError(
            "no vendor public key compiled in (VENDOR_PUBLIC_KEY_B64) and "
            "VIS_LICENSE_PUBKEY is unset — this build cannot verify licenses."
        )
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(raw))


def sign_license(payload: dict, private_key_b64: str) -> dict:
    """VENDOR-SIDE: wrap a payload with its Ed25519 signature. Used by the
    license-issuing tool, never by the deployed app."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    sig = key.sign(_canonical(payload))
    return {"payload": payload, "signature": base64.b64encode(sig).decode("ascii")}


def verify_document(doc: dict) -> dict:
    """Verify a {payload, signature} document; return the payload or raise."""
    from cryptography.exceptions import InvalidSignature

    try:
        payload, signature = doc["payload"], doc["signature"]
    except (KeyError, TypeError) as exc:
        raise LicenseError("malformed license file (expected payload+signature)") from exc
    try:
        _public_key().verify(base64.b64decode(signature), _canonical(payload))
    except InvalidSignature as exc:
        raise LicenseError(
            "license signature is INVALID — the file was edited or is not issued "
            "by the vendor. Contact support for a genuine license."
        ) from exc
    return payload


# ---- loading -------------------------------------------------------------
def _candidate_paths() -> list[Path]:
    paths = []
    env = os.environ.get(LICENSE_ENV)
    if env:
        paths.append(Path(env))
    for d in (Path.home() / ".vision-inspection", Path.cwd()):
        paths.extend(d / n for n in _DEFAULT_NAMES)
    return paths


def find_license_file() -> Path | None:
    return next((p for p in _candidate_paths() if p.is_file()), None)


def load_license(path: Path | None = None) -> License:
    """Load + cryptographically verify the license. Raises LicenseError."""
    path = path or find_license_file()
    if path is None:
        raise LicenseError(
            "no license file found (looked for VIS_LICENSE, "
            "~/.vision-inspection/vision.lic, ./vision.lic). "
            "Install the license issued for this station."
        )
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise LicenseError(f"cannot read license {path}: {exc}") from exc
    p = verify_document(doc)
    return License(
        license_id=str(p.get("license_id", "")),
        customer=str(p.get("customer", "")),
        packs=frozenset(p.get("packs", ())),
        machines=tuple(p.get("machines", ()) or ()),
        seats=int(p.get("seats", 1)),
        issued=str(p.get("issued", "")),
        expires=p.get("expires") or None,
        grace_days=int(p.get("grace_days", 0)),
        path=Path(path),
        raw=p,
    )


# ---- process-wide access -------------------------------------------------
_ACTIVE: License | None = None
_CHECKED = False


def active_license(reload: bool = False) -> License | None:
    """The verified license for this process, or None if absent/invalid.
    Never raises — callers that must enforce use ``require_pack``/``check_valid``."""
    global _ACTIVE, _CHECKED
    if reload:
        _CHECKED = False
    if not _CHECKED:
        _CHECKED = True
        try:
            lic = load_license()
            lic.check_valid()
            _ACTIVE = lic
            log.info("license OK: %s", lic.audit_summary())
        except LicenseError as exc:
            _ACTIVE = None
            log.warning("no valid license: %s", exc)
    return _ACTIVE


def unlicensed_mode() -> bool:
    """True when the app runs without a license. Permitted for development
    (all packs available); refused on a line PC via VIS_LICENSE_REQUIRED=1."""
    return active_license() is None


def license_required() -> bool:
    return os.environ.get("VIS_LICENSE_REQUIRED", "").strip() in ("1", "true", "yes")


def entitled_packs() -> frozenset[str] | None:
    """Packs this installation may use; None = unrestricted (dev, unlicensed)."""
    lic = active_license()
    if lic is None:
        if license_required():
            raise LicenseError(
                "VIS_LICENSE_REQUIRED is set but no valid license is installed — "
                "refusing to start. Install the station's license file."
            )
        return None
    return lic.packs


def has_pack(pack: str) -> bool:
    packs = entitled_packs()
    return True if packs is None else pack in packs


def require_pack(pack: str, what: str = "this feature") -> None:
    if not has_pack(pack):
        lic = active_license()
        who = f"license {lic.license_id}" if lic else "this installation"
        raise LicenseError(
            f"{what} requires the '{pack}' capability pack, which {who} does not "
            "include. Contact Control Print to add it."
        )
