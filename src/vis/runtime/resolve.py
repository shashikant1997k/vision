"""Resolve a recipe's batch-fed fields against the values entered at batch start.

A recipe taught with "Matches batch field" inspections is reusable across batches:
the lot/MFG/expiry/MRP are entered when the batch starts, and this rewrites those
inspections into concrete "contains" checks for the run. Inspections that aren't
batch-fed pass through unchanged.
"""

from __future__ import annotations

from ..domain.entities import Recipe, Region, ToolSpec


def required_batch_fields(recipe: Recipe) -> list[str]:
    """Field keys (lot/mfg/expiry/mrp/...) the recipe expects at batch start."""
    fields: list[str] = []
    for region in recipe.regions:
        for tool in region.tools:
            if (tool.config or {}).get("match") == "batch_field":
                field = tool.config.get("field", "")
                if field and field not in fields:
                    fields.append(field)
    return fields


def resolve_batch_fields(recipe: Recipe, batch_data: dict | None) -> Recipe:
    """Return a copy of `recipe` with batch_field inspections resolved to a
    concrete contains-match using `batch_data` (a value still missing leaves the
    inspection as 'any text read')."""
    data = batch_data or {}
    regions = []
    for region in recipe.regions:
        tools = []
        for tool in region.tools:
            config = dict(tool.config or {})
            if config.get("match") == "batch_field":
                value = str(data.get(config.get("field", ""), "") or "")
                if value:
                    # keep everything else (rotation, required, trained font, …)
                    resolved = dict(config)
                    resolved.pop("field", None)
                    resolved["match"] = "contains"
                    resolved["expected"] = value
                    resolved.setdefault("uppercase", True)
                    config = resolved
                # else: leave as batch_field → tool passes if any text is read
            tools.append(ToolSpec(tool.tool_id, tool.tool_type, tool.roi, config))
        regions.append(
            Region(
                region.region_id, region.name, region.roi, region.reject_output, tools,
                pass_logic=getattr(region, "pass_logic", "all"),
                fixture=getattr(region, "fixture", None),
            )
        )
    return Recipe(
        recipe.recipe_id, recipe.product, recipe.version, regions,
        image_rotation=getattr(recipe, "image_rotation", 0),
    )
