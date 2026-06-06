from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """The output of one inspection tool on one ROI."""

    tool_id: str
    passed: bool
    measured_value: str | None = None
    expected_value: str | None = None
    confidence: float | None = None
    model_version: str | None = None  # locked-model traceability (D-007)
    detail: dict[str, Any] = field(default_factory=dict)


class InspectionTool(ABC):
    """Common interface for ALL inspection tools — classic and (later) AI.

    The runtime and the teach UI treat every tool identically, so AI tools
    plug in exactly like classic ones (D-004). Implementations receive a
    pre-cropped ROI image and return a ToolResult.
    """

    type: str = "base"

    def __init__(self, tool_id: str, config: dict[str, Any] | None = None) -> None:
        self.tool_id = tool_id
        self.config = config or {}

    @abstractmethod
    def inspect(self, roi_image) -> ToolResult:
        """Inspect a pre-cropped ROI image and return a result."""
