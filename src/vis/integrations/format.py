from __future__ import annotations

import json
from dataclasses import dataclass, field

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


# --- configurable Output Template (CodeScan-style host/PLC/MES output) --------
# A site defines HOW each verified result is emitted to the line PLC, printer or
# MES: a token order, field separator, prefix/suffix wrapper, PASS/FAIL tokens
# and a bad-read marker. Tokens: "result", "frame_id", "camera_id", "region_id",
# "reject_output", a tool id (its read value), or "*" for every field value.
_META_TOKENS = {"frame_id", "camera_id", "region_id", "reject_output"}


@dataclass
class OutputTemplate:
    name: str = "default"
    enabled: bool = False
    transport: str = "tcp"  # tcp | serial
    prefix: str = ""
    suffix: str = ""
    ok_token: str = "PASS"
    nok_token: str = "FAIL"
    bad_read_token: str = ""  # emitted for a field that did not read
    separator: str = "|"
    terminator: str = "\\r\\n"  # stored with literal escapes; decoded on format
    fields: list[str] = field(default_factory=lambda: ["result", "*"])

    def to_dict(self) -> dict:
        return {
            "name": self.name, "enabled": self.enabled, "transport": self.transport,
            "prefix": self.prefix, "suffix": self.suffix, "ok_token": self.ok_token,
            "nok_token": self.nok_token, "bad_read_token": self.bad_read_token,
            "separator": self.separator, "terminator": self.terminator,
            "fields": list(self.fields),
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> OutputTemplate:
        d = d or {}
        base = cls()
        return cls(
            name=d.get("name", base.name),
            enabled=bool(d.get("enabled", base.enabled)),
            transport=d.get("transport", base.transport),
            prefix=d.get("prefix", base.prefix),
            suffix=d.get("suffix", base.suffix),
            ok_token=d.get("ok_token", base.ok_token),
            nok_token=d.get("nok_token", base.nok_token),
            bad_read_token=d.get("bad_read_token", base.bad_read_token),
            separator=d.get("separator", base.separator),
            terminator=d.get("terminator", base.terminator),
            fields=list(d.get("fields") or base.fields),
        )


def _decode_escapes(s: str) -> str:
    return s.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


def _is_bad_read(value) -> bool:
    return value is None or value == "" or (isinstance(value, str) and "?" in value)


def format_template(result: RegionResult, template: OutputTemplate) -> str:
    """Render a result through a configurable Output Template (the format the
    line PLC/printer/MES expects)."""
    rec = result_to_record(result)
    fields = rec["fields"]

    def render_value(value) -> str:
        return template.bad_read_token if _is_bad_read(value) else str(value)

    def render_token(token: str) -> str:
        if token == "result":
            return template.ok_token if result.passed else template.nok_token
        if token in ("*", "fields", "all"):
            return template.separator.join(render_value(v) for v in fields.values())
        if token in _META_TOKENS:
            v = rec.get(token)
            return "" if v is None else str(v)
        if token in fields:
            return render_value(fields[token])
        return ""  # unknown token → empty column (keeps the layout fixed)

    body = template.separator.join(render_token(t) for t in template.fields)
    return template.prefix + body + template.suffix + _decode_escapes(template.terminator)
