"""Pure (non-Qt) teach logic: build a recipe from regions/tools, test it against
a reference image, and convert to a domain Recipe for saving. Kept separate from
the Qt window so it is fully unit-testable."""

from __future__ import annotations

from ..common.types import ROI
from ..domain.entities import Recipe, Region, ToolSpec
from ..engine.frame import Frame
from ..engine.pipeline import InspectionPipeline
from ..engine.pool import SyncPool


def tool_config(tool_type: str, expected: str) -> dict:
    """Build a tool config from a single 'expected' value, per tool type."""
    if tool_type == "code_verify":
        return {"gs1": True, "expected_data": expected} if expected else {"gs1": True}
    if tool_type == "ocv_text":
        return {"expected": expected, "uppercase": True}
    return {}


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
    ) -> None:
        self.regions[region_index].tools.append(ToolSpec(tool_id, tool_type, roi, config or {}))

    def to_recipe(self) -> Recipe:
        return Recipe(self.recipe_id, self.product, 1, list(self.regions))

    def test(self, image) -> list:
        """Run the in-progress recipe against a reference image (one frame)."""
        pipeline = InspectionPipeline(self.to_recipe(), SyncPool())
        frame = Frame("teach", 0, image, 0.0)
        return pipeline.process_frame(frame)
