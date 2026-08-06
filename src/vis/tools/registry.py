from __future__ import annotations

from typing import Any

from .base import InspectionTool

_REGISTRY: dict[str, type[InspectionTool]] = {}


def register(tool_cls: type[InspectionTool]) -> type[InspectionTool]:
    """Class decorator: register a tool under its `type`."""
    _REGISTRY[tool_cls.type] = tool_cls
    return tool_cls


def build_tool(
    tool_type: str, tool_id: str, config: dict[str, Any] | None = None
) -> InspectionTool:
    try:
        cls = _REGISTRY[tool_type]
    except KeyError as exc:
        raise KeyError(
            f"unknown tool type {tool_type!r}; registered: {sorted(_REGISTRY)}"
        ) from exc
    # capability-pack entitlement: a tool from an unlicensed pack never runs
    # (one of several enforcement points; see vis.licensing)
    from ..licensing import require_tool

    require_tool(tool_type)
    return cls(tool_id, config)


def registered_types() -> list[str]:
    """All tool types this build knows, licensed or not (teach UI shows locked
    ones as an upsell surface — use ``available_types`` for what can run)."""
    return sorted(_REGISTRY)


def available_types() -> list[str]:
    """Tool types this installation's license permits."""
    from ..licensing import tool_allowed

    return sorted(t for t in _REGISTRY if tool_allowed(t))
