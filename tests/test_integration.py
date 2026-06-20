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


def _synthetic(passed=True, lot="ABC123", date=""):
    from vis.engine.aggregator import RegionResult
    from vis.tools.base import ToolResult

    return RegionResult(
        frame_id=7, camera_id="cam1", region_id="front", reject_output="lane1",
        passed=passed,
        tool_results=[
            ToolResult(tool_id="lot", passed=bool(lot), measured_value=lot),
            ToolResult(tool_id="date", passed=bool(date), measured_value=date),
        ],
    )


def test_output_template_orders_fields_with_wrapper():
    from vis.integrations.format import OutputTemplate, format_template

    tpl = OutputTemplate(
        prefix="<", suffix=">", ok_token="OK", nok_token="NG", separator=",",
        terminator="\\r\\n", fields=["result", "lot", "date", "camera_id"],
        bad_read_token="NOREAD",
    )
    out = format_template(_synthetic(passed=True, lot="ABC123", date="0624"), tpl)
    assert out == "<OK,ABC123,0624,cam1>\r\n"


def test_output_template_marks_bad_read_and_fail():
    from vis.integrations.format import OutputTemplate, format_template

    tpl = OutputTemplate(ok_token="OK", nok_token="NG", separator="|",
                         terminator="", bad_read_token="NOREAD",
                         fields=["result", "lot", "date"])
    # a date that failed to read ('?' present) → bad-read token; overall FAIL
    out = format_template(_synthetic(passed=False, lot="ABC123", date="06?4"), tpl)
    assert out == "NG|ABC123|NOREAD"


def test_output_template_roundtrips_through_dict():
    from vis.integrations.format import OutputTemplate

    tpl = OutputTemplate(name="line3", enabled=True, fields=["result", "*"])
    assert OutputTemplate.from_dict(tpl.to_dict()) == tpl


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
