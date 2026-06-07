"""Reject / digital I/O layer.

  digital_io.py  DigitalIO interface + SimulatedIO (records) + ModbusTcpIO (real)
  reject.py      RejectController — applies eject delay then pulses the lane output

The runtime stays decoupled via runtime.RejectHandler; RejectController is the
concrete implementation that drives the ejector.
"""

from .digital_io import DigitalIO, ModbusTcpIO, SimulatedIO
from .reject import RejectController, RejectOutputConfig

__all__ = [
    "DigitalIO",
    "ModbusTcpIO",
    "RejectController",
    "RejectOutputConfig",
    "SimulatedIO",
]
