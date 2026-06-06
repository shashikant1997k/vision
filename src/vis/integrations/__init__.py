"""External integration — publish scanned/inspection data to third-party apps.

Decoupled from the engine: connectors subscribe to the EventBus and push results
over TCP/IP (D-014). Future protocols (OPC-UA, Profinet, MES/ERP) live here too.
"""
