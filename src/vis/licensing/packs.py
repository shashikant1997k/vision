"""Capability packs — the unit of sale.

The engine (cameras, recipes, batches, audit, HMI, PLC I/O) ships to every
customer. What varies is the **packs**: bundles of inspection tools plus the
models behind them. A site's license lists the packs it bought; the tool
registry offers exactly those.

Unlicensed packs stay VISIBLE but locked in the teach screen — the customer can
see what the platform does and ask for a quote (the same upsell surface Cognex
gets from per-tool license bits), while being unable to run them.

Adding a product line = adding a pack here (+ its tools), not touching the
engine. That is what makes label inspection, fill-level and sorting incremental
work rather than new applications.
"""

from __future__ import annotations

from dataclasses import dataclass

from .license import LicenseError, active_license, entitled_packs, has_pack

CORE = "core"  # always available: camera, recipe, batch, audit, reporting


@dataclass(frozen=True)
class Pack:
    key: str
    title: str
    description: str
    tools: tuple[str, ...] = ()      # tool_type ids this pack unlocks
    models: tuple[str, ...] = ()     # model files this pack is licensed to load


PACKS: dict[str, Pack] = {
    CORE: Pack(
        CORE, "Core Engine",
        "Camera, recipes, batches, audit trail, reporting, PLC I/O.",
        tools=("presence", "measure", "roi"),
    ),
    "pharma-ocv": Pack(
        "pharma-ocv", "Pharma Coding OCR/OCV",
        "Read and verify batch/MFG/EXP/MRP printing (OCR-B, inkjet, laser).",
        tools=("ocv_text", "ocr_text", "advance_ocv", "print_inspect"),
        models=("ocrab_svtr256.onnx", "textline_det.onnx"),
    ),
    "cij-dotmatrix": Pack(
        "cij-dotmatrix", "Dot-Matrix / CIJ Coding",
        "Continuous-inkjet dot-matrix character reading (5x7, 9x7).",
        tools=("ocv_text", "ocr_text"),
        models=("cij_svtr256.onnx",),
    ),
    "codes": Pack(
        "codes", "Barcode / 2D Codes",
        "1D barcodes, DataMatrix, QR, GS1 parsing and print-quality grading.",
        tools=("code_verify", "code_grade", "gs1"),
    ),
    "label-qc": Pack(
        "label-qc", "Label Inspection",
        "Label presence, position, skew, artwork match, print defects.",
        tools=("label_present", "artwork_match", "print_quality"),
    ),
    "fill-level": Pack(
        "fill-level", "Fill Level",
        "Bottle/vial fill percentage and under/over-fill rejection.",
        tools=("fill_level",),
    ),
    "sorting": Pack(
        "sorting", "Sorting & Grading",
        "Classification and grading for produce/parts (size, colour, defect).",
        tools=("classify", "grade"),
    ),
}


def all_packs() -> list[Pack]:
    return list(PACKS.values())


def licensed_packs() -> list[Pack]:
    """Packs this installation may actually run (CORE always included)."""
    return [p for p in PACKS.values() if p.key == CORE or has_pack(p.key)]


def pack_for_tool(tool_type: str) -> Pack | None:
    """Which pack unlocks a tool type (CORE tools return the core pack)."""
    for pack in PACKS.values():
        if tool_type in pack.tools:
            return pack
    return None


def tool_allowed(tool_type: str) -> bool:
    """True if the license permits this tool type. Unknown tools are treated as
    core (fail-open) so an engine update never bricks an existing recipe — the
    licensed *packs* are the gate, not an incomplete lookup table."""
    pack = pack_for_tool(tool_type)
    return True if pack is None or pack.key == CORE else has_pack(pack.key)


def require_tool(tool_type: str) -> None:
    """Enforce entitlement at tool construction (raises LicenseError)."""
    pack = pack_for_tool(tool_type)
    if pack is None or pack.key == CORE:
        return
    if not has_pack(pack.key):
        lic = active_license()
        who = f"license {lic.license_id}" if lic else "this installation"
        raise LicenseError(
            f"tool '{tool_type}' belongs to the '{pack.title}' pack ({pack.key}), "
            f"which {who} does not include. Contact Control Print to add it."
        )


def model_allowed(model_name: str) -> bool:
    """True if a licensed pack covers this model file. Models not claimed by any
    pack (e.g. a customer's own fine-tune) are allowed."""
    owners = [p for p in PACKS.values() if model_name in p.models]
    if not owners:
        return True
    return any(has_pack(p.key) for p in owners)


def entitlement_report() -> dict:
    """Everything the HMI 'About / License' screen needs."""
    lic = active_license()
    packs = entitled_packs()
    return {
        "licensed": lic is not None,
        "license": lic.audit_summary() if lic else None,
        "unrestricted": packs is None,
        "packs": [
            {
                "key": p.key,
                "title": p.title,
                "description": p.description,
                "enabled": p.key == CORE or has_pack(p.key),
            }
            for p in PACKS.values()
        ],
    }
