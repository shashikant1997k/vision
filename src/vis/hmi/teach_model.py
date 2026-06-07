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
    },
    {
        "key": "ocv_text",
        "label": "Read Text (OCR)",
        "expected_label": "Expected text, e.g. LOT42",
    },
]


# Match modes — how an inspection decides pass/fail. Supports both STATIC
# (fixed value) and VARIABLE (any readable / pattern) codes and text.
FIXED = "Fixed value"
ANY_CODE = "Any readable code"
CONTAINS = "Contains text"
PATTERN = "Matches pattern"

CODE_MODES = [FIXED, ANY_CODE, PATTERN]
TEXT_MODES = [FIXED, CONTAINS, PATTERN]


def modes_for(tool_type: str) -> list[str]:
    return CODE_MODES if tool_type == "code_verify" else TEXT_MODES


def value_hint(tool_type: str, mode: str) -> str:
    if mode == ANY_CODE:
        return "(no value needed — passes if a code is read)"
    if mode == PATTERN:
        return r"regex, e.g. \d{4}/\d{2} for a date or [A-Z0-9]+ for a serial"
    if mode == CONTAINS:
        return "text that must appear, e.g. LOT"
    if tool_type == "code_verify":
        return "exact code data, e.g. a fixed GS1 string"
    return "exact text, e.g. LOT42"


def build_config(tool_type: str, mode: str, value: str) -> dict:
    """Build a tool config from a match mode + value (static or variable)."""
    if tool_type == "code_verify":
        if mode == ANY_CODE:
            return {"gs1": True}
        if mode == PATTERN:
            return {"gs1": True, "pattern": value}
        return {"gs1": True, "expected_data": value}  # FIXED
    # ocv_text
    if mode == CONTAINS:
        return {"match": "contains", "expected": value, "uppercase": True}
    if mode == PATTERN:
        return {"match": "regex", "pattern": value, "uppercase": True}
    return {"match": "exact", "expected": value, "uppercase": True}  # FIXED


def read_config(tool_type: str, config: dict) -> tuple[str, str]:
    """Inverse of build_config: (mode, value) from a stored config."""
    if tool_type == "code_verify":
        if config.get("pattern"):
            return (PATTERN, config["pattern"])
        if "expected_data" in config:
            return (FIXED, config.get("expected_data", "") or "")
        return (ANY_CODE, "")
    match = config.get("match", "exact")
    if match == "contains":
        return (CONTAINS, config.get("expected", "") or "")
    if match == "regex":
        return (PATTERN, config.get("pattern", "") or "")
    return (FIXED, config.get("expected", "") or "")


def tool_config(tool_type: str, expected: str) -> dict:
    """Backwards-compatible helper: a single 'expected' value → config."""
    if tool_type == "code_verify" and not expected:
        return build_config(tool_type, ANY_CODE, "")
    return build_config(tool_type, FIXED, expected)


def expected_of(tool_type: str, config: dict) -> str:
    """The 'value' part of a config (mode-agnostic)."""
    return read_config(tool_type, config)[1]


class TeachModel:
    def __init__(self, product: str, recipe_id: str) -> None:
        self.product = product
        self.recipe_id = recipe_id
        self.regions: list[Region] = []

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
        return Recipe(self.recipe_id, self.product, 1, list(self.regions))

    def test(self, image) -> list:
        """Run the in-progress recipe against a reference image (one frame)."""
        pipeline = InspectionPipeline(self.to_recipe(), SyncPool())
        frame = Frame("teach", 0, image, 0.0)
        return pipeline.process_frame(frame)
