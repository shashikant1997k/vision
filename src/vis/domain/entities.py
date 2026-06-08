from __future__ import annotations

from dataclasses import dataclass, field

from ..common.types import ROI

# Lean subset of the data model used by the engine. The full model
# (Station, Camera, RejectOutput, Batch, InspectionResult, AuditEntry, ...)
# is documented in docs/04-system-architecture.md and will be backed by a
# database. Recipe -> Region -> ToolSpec mirrors decision D-010.


@dataclass
class ToolSpec:
    """Configuration of one inspection tool within a region."""

    tool_id: str
    tool_type: str
    roi: ROI  # relative to the region
    config: dict = field(default_factory=dict)


@dataclass
class Fixture:
    """Part locator: a template taught from the master image. At runtime the
    template is found in each frame and the offset is applied to every ROI in the
    region, so inspections follow the part as it shifts (part-location/fixturing).
    """

    template: bytes  # PNG-encoded grayscale template patch
    anchor_x: int  # template's taught top-left X in the frame
    anchor_y: int  # template's taught top-left Y in the frame
    search_margin: int = 80  # how far around the anchor to search
    min_score: float = 0.5  # min match score to trust the location


@dataclass
class Region:
    """One product position within a single camera FOV (a track/lane)."""

    region_id: str
    name: str
    roi: ROI  # within the camera frame
    reject_output: str  # which reject lane this region routes to
    tools: list[ToolSpec] = field(default_factory=list)
    pass_logic: str = "all"  # "all" required inspections pass, or "any" passes
    fixture: Fixture | None = None  # optional part locator


@dataclass
class Recipe:
    """Versioned inspection configuration for a product on one camera."""

    recipe_id: str
    product: str
    version: int
    regions: list[Region] = field(default_factory=list)
    image_rotation: int = 0  # rotate every frame this many degrees before inspecting


@dataclass
class CameraConfig:
    camera_id: str
    name: str
