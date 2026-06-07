from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from ..tools import build_tool  # importing the package registers built-in tools
from ..tools.base import ToolResult


@dataclass
class ToolTask:
    """A single unit of work sent to a worker: one tool on one cropped ROI.
    Carries only the small ROI image (crop-first) so it pickles cheaply."""

    frame_id: int
    camera_id: str
    region_id: str
    tool_id: str
    tool_type: str
    config: dict
    roi_image: np.ndarray


@dataclass
class ToolOutcome:
    frame_id: int
    camera_id: str
    region_id: str
    result: ToolResult


# Per-process cache of constructed tools. In production this is also where a
# warm ONNX Runtime session lives — loaded once per process, never per image.
_TOOL_CACHE: dict[tuple[str, str], object] = {}


def worker_init() -> None:
    """ProcessPool initializer. Production: load locked ONNX models here once."""
    return None


def run_tool_task(task: ToolTask) -> ToolOutcome:
    # Key on config too: the same tool_id can carry different config across recipe
    # versions / teach edits, and reusing a stale instance would be wrong.
    key = (task.tool_type, task.tool_id, json.dumps(task.config, sort_keys=True, default=str))
    tool = _TOOL_CACHE.get(key)
    if tool is None:
        tool = build_tool(task.tool_type, task.tool_id, task.config)
        _TOOL_CACHE[key] = tool
    result = tool.inspect(task.roi_image)
    return ToolOutcome(task.frame_id, task.camera_id, task.region_id, result)
