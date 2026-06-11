"""Pure (non-Qt) teach logic: build a recipe from regions/tools, test it against
a reference image, and convert to a domain Recipe for saving. Kept separate from
the Qt window so it is fully unit-testable."""

from __future__ import annotations

from ..common.types import ROI
from ..domain.entities import Recipe, Region, ToolSpec
from ..engine.frame import Frame
from ..engine.pipeline import InspectionPipeline
from ..engine.pool import SyncPool


# Inspection types shown in the teach palette (plain language ↔ internal type).
INSPECTION_TYPES = [
    {
        "key": "code_verify",
        "label": "Read Code (1D/2D / GS1)",
        "expected_label": "Expected code data (blank = accept any readable code)",
        "category": "read",
    },
    {
        "key": "ocv_text",
        "label": "Read Text (OCR)",
        "expected_label": "Expected text, e.g. LOT42",
        "category": "read",
    },
    {
        "key": "ocv_font",
        "label": "Verify Text (OCV — trained font)",
        "expected_label": "Expected text, e.g. LOT42",
        "category": "read",
    },
    {"key": "presence", "label": "Presence / Absence", "expected_label": "", "category": "inspect"},
    {"key": "measure", "label": "Measure (size)", "expected_label": "", "category": "inspect"},
    {"key": "color_check", "label": "Colour check", "expected_label": "", "category": "inspect"},
    {"key": "template_match", "label": "Match template (artwork)", "expected_label": "", "category": "inspect"},
]

# Tool types whose pass/fail is value/match based (the properties panel edits them).
MATCH_TOOLS = ("code_verify", "ocv_text", "ocv_font")

# Config keys that carry a trained font — must survive match-mode edits.
FONT_KEYS = ("font", "font_name", "font_id", "dot_kernel", "min_area")


def default_config(tool_type: str) -> dict:
    """Sensible starting config when an inspection is first drawn."""
    return {
        "presence": {"mode": "present", "min_coverage": 0.05},
        "measure": {"axis": "width", "min_px": 10, "max_px": 100000},
        "color_check": {"target": [128, 128, 128], "tolerance": 40},
        "template_match": {},  # golden template captured from the drawn ROI
    }.get(tool_type, {})


# Match modes — how an inspection decides pass/fail. Supports STATIC (fixed),
# VARIABLE (any readable / pattern), and BATCH-FED (matches a value entered at
# batch start) codes and text.
FIXED = "Fixed value"
ANY_CODE = "Any readable code"
CONTAINS = "Contains text"
PATTERN = "Matches pattern"
BATCH_FIELD = "Matches batch field"

CODE_MODES = [FIXED, ANY_CODE, PATTERN]
# batch-field stays supported for legacy recipes but is no longer offered in teach
TEXT_MODES = [FIXED, CONTAINS, PATTERN]

ROTATIONS = [0, 90, 180, 270]

# Batch fields entered before each batch (the "fed before every batch" values).
BATCH_FIELDS = [
    ("lot", "Batch / B.No"),
    ("mfg", "MFG date"),
    ("expiry", "Expiry date"),
    ("mrp", "M.R.P"),
]
BATCH_FIELD_KEYS = [k for k, _ in BATCH_FIELDS]


def modes_for(tool_type: str) -> list[str]:
    return CODE_MODES if tool_type == "code_verify" else TEXT_MODES


def value_hint(tool_type: str, mode: str) -> str:
    if mode == ANY_CODE:
        return "(no value needed — passes if a code is read)"
    if mode == BATCH_FIELD:
        return "(value is entered at batch start — choose the field at right)"
    if mode == PATTERN:
        return r"regex, e.g. \d{4}/\d{2} for a date or [A-Z0-9]+ for a serial"
    if mode == CONTAINS:
        return "text that must appear, e.g. LOT"
    if tool_type == "code_verify":
        return "exact code data, e.g. a fixed GS1 string"
    return "exact text, e.g. LOT42"


def build_config(
    tool_type: str, mode: str, value: str, rotation: int = 0, field: str = ""
) -> dict:
    """Build a tool config from a match mode + value (+ rotation, batch field)."""
    if tool_type == "code_verify":
        if mode == ANY_CODE:
            cfg = {"gs1": True}
        elif mode == PATTERN:
            cfg = {"gs1": True, "pattern": value}
        else:
            cfg = {"gs1": True, "expected_data": value}  # FIXED
    elif mode == BATCH_FIELD:
        cfg = {"match": "batch_field", "field": field, "uppercase": True}
    elif mode == CONTAINS:
        cfg = {"match": "contains", "expected": value, "uppercase": True}
    elif mode == PATTERN:
        cfg = {"match": "regex", "pattern": value, "uppercase": True}
    else:
        cfg = {"match": "exact", "expected": value, "uppercase": True}  # FIXED
    if rotation:
        cfg["rotation"] = int(rotation)
    return cfg


def read_config(tool_type: str, config: dict) -> dict:
    """Inverse of build_config: {mode, value, rotation, field} from a config."""
    rotation = int(config.get("rotation", 0) or 0)
    if tool_type == "code_verify":
        if config.get("pattern"):
            mode, value = PATTERN, config["pattern"]
        elif "expected_data" in config:
            mode, value = FIXED, config.get("expected_data", "") or ""
        else:
            mode, value = ANY_CODE, ""
        return {"mode": mode, "value": value, "rotation": rotation, "field": ""}

    match = config.get("match", "exact")
    if match == "batch_field":
        return {"mode": BATCH_FIELD, "value": "", "rotation": rotation, "field": config.get("field", "")}
    if match == "contains":
        return {"mode": CONTAINS, "value": config.get("expected", "") or "", "rotation": rotation, "field": ""}
    if match == "regex":
        return {"mode": PATTERN, "value": config.get("pattern", "") or "", "rotation": rotation, "field": ""}
    return {"mode": FIXED, "value": config.get("expected", "") or "", "rotation": rotation, "field": ""}


def tool_config(tool_type: str, expected: str) -> dict:
    """Backwards-compatible helper: a single 'expected' value → config."""
    if tool_type == "code_verify" and not expected:
        return build_config(tool_type, ANY_CODE, "")
    return build_config(tool_type, FIXED, expected)


def expected_of(tool_type: str, config: dict) -> str:
    """The 'value' part of a config (mode-agnostic)."""
    return read_config(tool_type, config)["value"]


class TeachModel:
    def __init__(self, product: str, recipe_id: str) -> None:
        self.product = product
        self.recipe_id = recipe_id
        self.regions: list[Region] = []
        self.image_rotation = 0

    def add_region(self, name: str, roi: ROI, reject_output: str) -> int:
        region_id = f"region{len(self.regions) + 1}"
        self.regions.append(Region(region_id, name, roi, reject_output, []))
        return len(self.regions) - 1

    def add_tool(
        self, region_index: int, tool_id: str, tool_type: str, roi: ROI, config: dict | None = None
    ) -> int:
        self.regions[region_index].tools.append(ToolSpec(tool_id, tool_type, roi, config or {}))
        return len(self.regions[region_index].tools) - 1

    def remove_region(self, region_index: int) -> None:
        del self.regions[region_index]

    def remove_tool(self, region_index: int, tool_index: int) -> None:
        del self.regions[region_index].tools[tool_index]

    def to_recipe(self) -> Recipe:
        return Recipe(
            self.recipe_id, self.product, 1, list(self.regions),
            image_rotation=self.image_rotation,
        )

    def test(self, image) -> list:
        """Run the in-progress recipe against a raw reference image (the pipeline
        applies the recipe's image rotation)."""
        pipeline = InspectionPipeline(self.to_recipe(), SyncPool())
        frame = Frame("teach", 0, image, 0.0)
        return pipeline.process_frame(frame)
