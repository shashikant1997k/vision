from __future__ import annotations

import json

from ..engine.aggregator import RegionResult


def result_to_record(result: RegionResult) -> dict:
    """Flatten a region result into the payload a third-party app receives."""
    return {
        "frame_id": result.frame_id,
        "camera_id": result.camera_id,
        "region_id": result.region_id,
        "result": "PASS" if result.passed else "FAIL",
        "reject_output": result.reject_output,
        "fields": {tr.tool_id: tr.measured_value for tr in result.tool_results},
    }


def format_json(result: RegionResult, terminator: str = "\r\n") -> str:
    """Line-framed JSON (JSONL) — easy for any TCP consumer to parse."""
    return json.dumps(result_to_record(result)) + terminator


def format_delimited(result: RegionResult, sep: str = "|", terminator: str = "\r\n") -> str:
    """Delimited record for host systems that expect a fixed layout. A future
    version makes the column template fully configurable per connector."""
    rec = result_to_record(result)
    cols = [rec["frame_id"], rec["camera_id"], rec["region_id"], rec["result"], rec["reject_output"]]
    cols += list(rec["fields"].values())
    return sep.join("" if c is None else str(c) for c in cols) + terminator
