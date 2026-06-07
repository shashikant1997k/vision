from __future__ import annotations

import csv
import html
import io
import os
from pathlib import Path

from sqlalchemy import select

from ..db.models import Batch, ESignature, InspectionResult, Product, ToolResultRow


def _disp(value) -> str:
    """Make a value safe/readable for CSV/HTML (control chars like the GS1 0x1d
    separator become a visible token)."""
    if value is None:
        return ""
    return str(value).replace("\x1d", "<GS>")


def get_release_signature(session, batch_id: int) -> ESignature | None:
    return session.execute(
        select(ESignature)
        .where(ESignature.entity_type == "batch", ESignature.entity_id == str(batch_id))
        .order_by(ESignature.id.desc())
    ).scalars().first()


def compute_summary(session, batch_id: int) -> dict:
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise ValueError(f"batch {batch_id} not found")
    product = session.get(Product, batch.product_id) if batch.product_id else None

    results = session.execute(
        select(InspectionResult).where(InspectionResult.batch_id == batch_id)
    ).scalars().all()
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    rejects_by_lane: dict[str, int] = {}
    for r in results:
        if not r.passed:
            lane = r.reject_output or "?"
            rejects_by_lane[lane] = rejects_by_lane.get(lane, 0) + 1

    defects_by_tool: dict[str, int] = {}
    if results:
        ids = [r.id for r in results]
        failed_tools = session.execute(
            select(ToolResultRow).where(
                ToolResultRow.inspection_result_id.in_(ids),
                ToolResultRow.passed.is_(False),
            )
        ).scalars().all()
        for tr in failed_tools:
            defects_by_tool[tr.tool_key] = defects_by_tool.get(tr.tool_key, 0) + 1

    return {
        "batch_no": batch.batch_no,
        "status": batch.status,
        "product": product.name if product else None,
        "recipe_version": batch.recipe_version,
        "started_at": batch.started_at,
        "closed_at": batch.closed_at,
        "mfg_date": batch.mfg_date,
        "exp_date": batch.exp_date,
        "mrp": batch.mrp,
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(100 * passed / total, 2) if total else 0.0,
        "rejects_by_lane": rejects_by_lane,
        "defects_by_tool": dict(sorted(defects_by_tool.items(), key=lambda kv: -kv[1])),
    }


def to_csv(session, batch_id: int) -> str:
    results = session.execute(
        select(InspectionResult)
        .where(InspectionResult.batch_id == batch_id)
        .order_by(InspectionResult.id)
    ).scalars().all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["frame_id", "region", "result", "reject_lane", "tool", "tool_result",
         "measured", "expected", "grade"]
    )
    for r in results:
        for tr in r.tool_results:
            grade = (tr.detail or {}).get("grade", {}).get("overall", "")
            writer.writerow(
                [
                    r.frame_id,
                    r.region_key,
                    "PASS" if r.passed else "FAIL",
                    r.reject_output or "",
                    tr.tool_key,
                    "PASS" if tr.passed else "FAIL",
                    _disp(tr.measured_value),
                    _disp(tr.expected_value),
                    grade,
                ]
            )
    return buf.getvalue()


def write_batch_report(session_factory, batch_id: int, directory: str) -> tuple[str, str]:
    """Write the signed HTML report + CSV export for a batch. Returns the paths."""
    os.makedirs(directory, exist_ok=True)
    with session_factory() as s:
        summary = compute_summary(s, batch_id)
        signature = get_release_signature(s, batch_id)
        signature_line = ""
        if signature is not None:
            signature_line = (
                f"Released by user#{signature.user_id} — {signature.meaning} @ {signature.ts}"
            )
        html_text = to_html(summary, signature_line=signature_line)
        csv_text = to_csv(s, batch_id)

    html_path = os.path.join(directory, f"batch_{batch_id}.html")
    csv_path = os.path.join(directory, f"batch_{batch_id}.csv")
    Path(html_path).write_text(html_text, encoding="utf-8")
    Path(csv_path).write_text(csv_text, encoding="utf-8")
    return html_path, csv_path


def to_html(summary: dict, signature_line: str = "") -> str:
    def kv_table(pairs):
        return "".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(_disp(v))}</td></tr>"
            for k, v in pairs
        )

    def count_table(d, label):
        if not d:
            return f"<tr><td colspan=2>no {label}</td></tr>"
        return "".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k, v in d.items()
        )

    overview = kv_table(
        [
            ("Batch No", summary["batch_no"]),
            ("Product", summary["product"]),
            ("Recipe version", summary["recipe_version"]),
            ("Status", summary["status"]),
            ("Started", summary["started_at"]),
            ("Closed", summary["closed_at"]),
            ("MFG / EXP / MRP", f"{summary['mfg_date']} / {summary['exp_date']} / {summary['mrp']}"),
            ("Total inspected", summary["total"]),
            ("Passed", summary["passed"]),
            ("Failed", summary["failed"]),
            ("Pass rate %", summary["pass_rate"]),
        ]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Batch Report {html.escape(str(summary['batch_no']))}</title>
<style>body{{font-family:sans-serif;margin:2rem;color:#222}}table{{border-collapse:collapse;margin:.5rem 0 1.5rem}}
td,th{{border:1px solid #ccc;padding:4px 12px;text-align:left}}h1{{font-size:1.3rem}}
.sig{{margin-top:2rem;padding:1rem;border:1px solid #444;background:#fafafa}}
.note{{color:#888;font-size:.8rem;margin-top:1rem}}</style></head>
<body>
<h1>Batch Inspection Report &mdash; {html.escape(str(summary['batch_no']))}</h1>
<table>{overview}</table>
<h2>Rejects by lane</h2><table><tr><th>Lane</th><th>Count</th></tr>{count_table(summary['rejects_by_lane'], 'rejects')}</table>
<h2>Defects by tool (Pareto)</h2><table><tr><th>Tool</th><th>Count</th></tr>{count_table(summary['defects_by_tool'], 'defects')}</table>
<div class="sig">{html.escape(signature_line) if signature_line else 'Not yet released.'}</div>
<p class="note">Code grades are approximate process-control indicators, NOT certified ISO 15415/15416 verifier grades.</p>
</body></html>"""
