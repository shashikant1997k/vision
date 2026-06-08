"""External integration — publish scanned/inspection data to third-party apps.

Decoupled from the engine: connectors subscribe to the EventBus and push results
over TCP/IP (D-014), or to a line PLC over a fieldbus (Modbus/EtherNet-IP).
Future protocols (OPC-UA, PROFINET gateway, MES/ERP) live here too.
"""

from .plc import EtherNetIpPlcLink, ModbusPlcLink, PlcLink, RecordingPlcLink
from .publisher import ResultPublisher
from .tcp import TcpResultClient, TcpResultServer

__all__ = [
    "EtherNetIpPlcLink",
    "ModbusPlcLink",
    "PlcLink",
    "RecordingPlcLink",
    "ResultPublisher",
    "TcpResultClient",
    "TcpResultServer",
]
