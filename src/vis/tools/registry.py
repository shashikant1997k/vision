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
    return cls(tool_id, config)


def registered_types() -> list[str]:
    return sorted(_REGISTRY)
