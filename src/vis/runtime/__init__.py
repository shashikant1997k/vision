"""Live runtime — drives acquisition → inspection → reject across cameras.

  runner.py     InspectionRunner — one acquisition thread per camera → pool → aggregate
  stats.py      LiveStats — thread-safe running counters (per camera + totals)
  live_view.py  LiveView — latest frame + results per camera (for the HMI display)
  reject.py     RejectHandler — where reject routing / ejector I/O happens
"""

from .live_view import LiveView
from .overlay import draw_layout, draw_overlay
from .reject import RecordingRejectHandler, RejectHandler
from .runner import InspectionRunner
from .stats import LiveStats

__all__ = [
    "InspectionRunner",
    "LiveStats",
    "LiveView",
    "RecordingRejectHandler",
    "RejectHandler",
    "draw_layout",
    "draw_overlay",
]
