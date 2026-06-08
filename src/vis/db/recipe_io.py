"""Recipe import / export — portable JSON for moving recipes between stations,
backups, and offline review. Includes regions, inspections, the part locator,
image rotation, and pass logic. Importing creates a draft (re-approval required —
recipes are version-controlled and signed, D-010/Part 11)."""

from __future__ import annotations

import json

from ..common.types import ROI
from ..domain.entities import Recipe as DomainRecipe
from ..domain.entities import Region as DomainRegion
from ..domain.entities import ToolSpec
from .store import RecipeRepository, _fixture_from_json, _fixture_to_json

FORMAT = "vis-recipe/1"


def _roi(roi) -> dict:
    return {"x": roi.x, "y": roi.y, "w": roi.w, "h": roi.h}


def recipe_to_dict(recipe) -> dict:
    return {
        "format": FORMAT,
        "product": recipe.product,
        "recipe_id": recipe.recipe_id,
        "version": recipe.version,
        "image_rotation": getattr(recipe, "image_rotation", 0),
        "regions": [
            {
                "region_id": r.region_id,
                "name": r.name,
                "roi": _roi(r.roi),
                "reject_output": r.reject_output,
                "pass_logic": getattr(r, "pass_logic", "all"),
                "fixture": _fixture_to_json(getattr(r, "fixture", None)),
                "tools": [
                    {"tool_id": t.tool_id, "tool_type": t.tool_type, "roi": _roi(t.roi), "config": t.config}
                    for t in r.tools
                ],
            }
            for r in recipe.regions
        ],
    }


def dict_to_recipe(data: dict) -> DomainRecipe:
    regions = []
    for rd in data.get("regions", []):
        tools = [
            ToolSpec(t["tool_id"], t["tool_type"], ROI(**t["roi"]), dict(t.get("config") or {}))
            for t in rd.get("tools", [])
        ]
        regions.append(
            DomainRegion(
                rd["region_id"], rd["name"], ROI(**rd["roi"]), rd.get("reject_output", "default"),
                tools, pass_logic=rd.get("pass_logic", "all"), fixture=_fixture_from_json(rd.get("fixture")),
            )
        )
    return DomainRecipe(
        recipe_id=data.get("recipe_id", "imported"),
        product=data.get("product", "Imported"),
        version=data.get("version", 1),
        regions=regions,
        image_rotation=data.get("image_rotation", 0),
    )


def export_recipe(session_factory, recipe_id: int, path: str) -> str:
    recipe = RecipeRepository(session_factory).load(recipe_id)
    with open(path, "w") as f:
        json.dump(recipe_to_dict(recipe), f, indent=2)
    return path


def export_recipe_obj(recipe, path: str) -> str:
    """Export an in-memory domain recipe (e.g. the in-progress teach recipe)."""
    with open(path, "w") as f:
        json.dump(recipe_to_dict(recipe), f, indent=2)
    return path


def import_recipe(session_factory, path: str, user_id: int) -> int:
    with open(path) as f:
        data = json.load(f)
    return RecipeRepository(session_factory).save_draft(dict_to_recipe(data), user_id=user_id)
