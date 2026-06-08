from __future__ import annotations

from ..common.events import EventBus
from ..common.types import crop
from ..domain.entities import Recipe
from .aggregator import RegionResult, aggregate
from .frame import Frame
from .workers import ToolTask


class InspectionPipeline:
    """Frame -> crop regions & ROIs -> worker pool -> aggregate -> reject + audit.

    Mirrors the engine subsystem in docs/04. Results and rejects are published
    on the event bus so audit, reporting, and (Phase 2) serialization can
    subscribe without the engine knowing about them.
    """

    def __init__(self, recipe: Recipe, pool, bus: EventBus | None = None) -> None:
        self.recipe = recipe
        self.pool = pool
        self.bus = bus or EventBus()

    def _build_tasks(self, frame: Frame) -> list[ToolTask]:
        image = frame.image
        rotation = getattr(self.recipe, "image_rotation", 0)
        if rotation:
            from ..tools.transform import rotate_image

            image = rotate_image(image, rotation)
        tasks: list[ToolTask] = []
        for region in self.recipe.regions:
            roi = region.roi
            fixture = getattr(region, "fixture", None)
            if fixture is not None:
                from ..common.types import ROI
                from ..runtime.locator import locate

                dx, dy, score = locate(image, fixture)
                if score >= fixture.min_score and (dx or dy):
                    roi = ROI(roi.x + dx, roi.y + dy, roi.w, roi.h)  # follow the part
            region_img = crop(image, roi)
            for tool in region.tools:
                roi_img = crop(region_img, tool.roi)
                tasks.append(
                    ToolTask(
                        frame_id=frame.frame_id,
                        camera_id=frame.camera_id,
                        region_id=region.region_id,
                        tool_id=tool.tool_id,
                        tool_type=tool.tool_type,
                        config=tool.config,
                        roi_image=roi_img.copy(),  # contiguous copy for pickling
                    )
                )
        return tasks

    def process_frame(self, frame: Frame) -> list[RegionResult]:
        outcomes = self.pool.map(self._build_tasks(frame))
        results = aggregate(outcomes, self.recipe)
        for r in results:
            self.bus.publish("inspection.result", r)
            if not r.passed:
                self.bus.publish("inspection.reject", r)
        return results
