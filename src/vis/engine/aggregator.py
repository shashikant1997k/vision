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


def _region_passed(tool_results, pass_logic: str, required_of: dict[str, bool]) -> bool:
    """Apply the product's pass/fail rule over its REQUIRED inspections.

    Optional inspections (required=False) are logged but don't affect the
    product result, so you can e.g. require only the QR and treat the text as
    informational, or require everything (a single text fail → reject).
    """
    required = [tr for tr in tool_results if required_of.get(tr.tool_id, True)]
    if not required:
        return True
    if pass_logic == "any":
        return any(tr.passed for tr in required)
    return all(tr.passed for tr in required)


def aggregate(outcomes: list[ToolOutcome], recipe: Recipe) -> list[RegionResult]:
    """Group tool outcomes by region and apply each product's configured
    pass/fail rule (all / any, with per-inspection Required flags). Routes each
    region to its reject output."""
    region_meta = {}
    for r in recipe.regions:
        required_of = {t.tool_id: (t.config or {}).get("required", True) for t in r.tools}
        region_meta[r.region_id] = (r.reject_output, getattr(r, "pass_logic", "all"), required_of)

    grouped: dict[tuple[int, str, str], list[ToolOutcome]] = {}
    for o in outcomes:
        grouped.setdefault((o.frame_id, o.camera_id, o.region_id), []).append(o)

    results: list[RegionResult] = []
    for (frame_id, camera_id, region_id), outs in grouped.items():
        tool_results = [o.result for o in outs]
        reject_output, pass_logic, required_of = region_meta.get(region_id, ("default", "all", {}))
        passed = _region_passed(tool_results, pass_logic, required_of)
        results.append(
            RegionResult(
                frame_id=frame_id,
                camera_id=camera_id,
                region_id=region_id,
                reject_output=reject_output,
                passed=passed,
                tool_results=tool_results,
            )
        )
    return results
