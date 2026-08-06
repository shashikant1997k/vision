"""Licensing — signed licenses, capability packs, encrypted models.

Public surface::

    from vis.licensing import has_pack, require_tool, active_license
    from vis.licensing import machine_fingerprint, entitlement_report

The vendor-side tools (issuing licenses, encrypting model packages) live in
``vis.licensing.issue`` and are exposed by the ``vis-license`` CLI; they need
the private signing key and are never used by a deployed station.
"""

from .fingerprint import fingerprint_report, machine_fingerprint
from .license import (
    License,
    LicenseError,
    active_license,
    entitled_packs,
    has_pack,
    license_required,
    load_license,
    require_pack,
    unlicensed_mode,
)
from .model_crypto import ModelDecryptError, load_model_bytes, resolve_model_path
from .packs import (
    PACKS,
    Pack,
    all_packs,
    entitlement_report,
    licensed_packs,
    model_allowed,
    pack_for_tool,
    require_tool,
    tool_allowed,
)

__all__ = [
    "License", "LicenseError", "active_license", "entitled_packs", "has_pack",
    "license_required", "load_license", "require_pack", "unlicensed_mode",
    "machine_fingerprint", "fingerprint_report",
    "ModelDecryptError", "load_model_bytes", "resolve_model_path",
    "PACKS", "Pack", "all_packs", "entitlement_report", "licensed_packs",
    "model_allowed", "pack_for_tool", "require_tool", "tool_allowed",
]
