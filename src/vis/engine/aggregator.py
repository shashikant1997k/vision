from __future__ import annotations

from dataclasses import dataclass

from ..domain.entities import Recipe
from ..tools.base import ToolResult
from .workers import ToolOutcome


@dataclass
class RegionResult:
    """Per-product (per-region) pass/fail — one frame yields N of these."""

    frame_id: int
    camera_id: str
    region_id: str
    reject_output: str
    passed: bool
    tool_results: list[ToolResult]


def aggregate(outcomes: list[ToolOutcome], recipe: Recipe) -> list[RegionResult]:
    """Group tool outcomes by region and apply pass/fail logic (currently AND
    of all tools). Routes each region to its configured reject output."""
    reject_of = {r.region_id: r.reject_output for r in recipe.regions}
    grouped: dict[tuple[int, str, str], list[ToolOutcome]] = {}
    for o in outcomes:
        grouped.setdefault((o.frame_id, o.camera_id, o.region_id), []).append(o)

    results: list[RegionResult] = []
    for (frame_id, camera_id, region_id), outs in grouped.items():
        tool_results = [o.result for o in outs]
        passed = all(tr.passed for tr in tool_results)
        results.append(
            RegionResult(
                frame_id=frame_id,
                camera_id=camera_id,
                region_id=region_id,
                reject_output=reject_of.get(region_id, "default"),
                passed=passed,
                tool_results=tool_results,
            )
        )
    return results
