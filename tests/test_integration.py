import json
import socket
import time

from vis.cli import build_demo_recipe
from vis.common.events import EventBus
from vis.engine.camera import FakeCamera
from vis.engine.pipeline import InspectionPipeline
from vis.engine.pool import SyncPool
from vis.integrations.format import format_json, result_to_record
from vis.integrations.publisher import ResultPublisher
from vis.integrations.tcp import TcpResultServer


def _run_one(bus=None):
    recipe = build_demo_recipe()
    pipeline = InspectionPipeline(recipe, SyncPool(), bus)
    camera = FakeCamera("cam1", recipe, num_frames=1, defect_rate=0.0)
    return [r for f in camera.frames() for r in pipeline.process_frame(f)]


def test_result_record_shape():
    rec = result_to_record(_run_one()[0])
    assert rec["camera_id"] == "cam1"
    assert rec["result"] == "PASS"
    assert any(k.endswith("_lot") for k in rec["fields"])


def test_tcp_publish_to_connected_client():
    server = TcpResultServer(host="127.0.0.1", port=0)
    try:
        client = socket.create_connection(("127.0.0.1", server.port), timeout=2.0)
        client.settimeout(2.0)

        deadline = time.time() + 2.0
        while server.client_count < 1 and time.time() < deadline:
            time.sleep(0.01)
        assert server.client_count == 1

        bus = EventBus()
        bus.subscribe("inspection.result", ResultPublisher(server, format_json).on_result)
        _run_one(bus)

        line = client.recv(4096).decode("utf-8").splitlines()[0]
        rec = json.loads(line)
        assert rec["camera_id"] == "cam1"
        assert rec["result"] == "PASS"
        client.close()
    finally:
        server.close()
