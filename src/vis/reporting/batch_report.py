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

    from ..db.oee import compute_oee
    from ..db.reconciliation import compute_reconciliation

    return {
        "oee": compute_oee(session, batch_id),
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
        "reconciliation": compute_reconciliation(session, batch_id),
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


def _reject_images_html(session, batch_id: int, limit: int = 24) -> str:
    """Embed the archived reject images (product crops) as base64 data URIs so
    the report stays ONE portable file (email/print/regulator-safe). Newest
    first, capped at `limit` with the total noted."""
    import base64

    from sqlalchemy import select

    from ..db.models import FrameCapture

    rows = session.execute(
        select(FrameCapture)
        .where(FrameCapture.batch_id == batch_id, FrameCapture.passed.is_(False))
        .order_by(FrameCapture.id.desc())
    ).scalars().all()
    with_img = [r for r in rows if r.image_ref and os.path.isfile(r.image_ref)]
    if not with_img:
        return ""
    cells = []
    for r in with_img[:limit]:
        try:
            data = base64.b64encode(Path(r.image_ref).read_bytes()).decode("ascii")
        except OSError:
            continue
        cells.append(
            f'<figure style="display:inline-block;margin:6px;text-align:center">'
            f'<img src="data:image/png;base64,{data}" '
            f'style="max-width:260px;max-height:180px;border:2px solid #c33"/>'
            f"<figcaption>frame {r.frame_id} · {html.escape(r.camera_id)}"
            f" · {html.escape((r.created_at or '')[:19])}</figcaption></figure>"
        )
    if not cells:
        return ""
    note = (f" (showing latest {limit} of {len(with_img)})"
            if len(with_img) > limit else "")
    return f"<h2>Reject images{html.escape(note)}</h2><div>{''.join(cells)}</div>"


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
        images_html = _reject_images_html(s, batch_id)
        html_text = to_html(summary, signature_line=signature_line, images_html=images_html)
        csv_text = to_csv(s, batch_id)

    html_path = os.path.join(directory, f"batch_{batch_id}.html")
    csv_path = os.path.join(directory, f"batch_{batch_id}.csv")
    Path(html_path).write_text(html_text, encoding="utf-8")
    Path(csv_path).write_text(csv_text, encoding="utf-8")
    return html_path, csv_path


def to_html(summary: dict, signature_line: str = "", images_html: str = "") -> str:
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
    recon = summary.get("reconciliation") or {}
    recon_rows = kv_table(
        [
            ("Units in (issued)", recon.get("units_in")),
            ("Good accepted", recon.get("good")),
            ("Rejected", recon.get("rejected")),
            ("Samples removed", recon.get("samples_removed")),
            ("Recovered / reworked", recon.get("recovered")),
            ("Destroyed", recon.get("destroyed")),
            ("Accounted", recon.get("accounted")),
            ("Unaccounted", recon.get("unaccounted")),
            ("Yield %", recon.get("yield_pct")),
            ("Reconciliation %", recon.get("reconciliation_pct")),
            ("Within tolerance", recon.get("within_tolerance")),
            ("Reject-bin count", recon.get("reject_bin_count")),
            ("Reject-bin delta", recon.get("reject_bin_delta")),
            ("Unique serials", recon.get("unique_serials")),
            ("Duplicate serials", len(recon.get("duplicate_serials") or [])),
        ]
    ) if recon else ""
    recon_verdict = ""
    if recon:
        ok = recon.get("reconciled")
        if recon.get("units_in"):
            recon_verdict = (
                f"<p class='{'ok' if ok else 'bad'}'>Batch "
                f"{'RECONCILES' if ok else 'DOES NOT reconcile'}.</p>"
            )
    recon_section = (
        f"<h2>Reconciliation</h2>{recon_verdict}<table>{recon_rows}</table>" if recon else ""
    )

    oee = summary.get("oee") or {}
    oee_section = ""
    if oee:
        def _pct(x):
            return f"{round(100 * x, 1)}%" if x else "—"
        oee_rows = kv_table([
            ("OEE", _pct(oee["oee"])),
            ("Availability", _pct(oee["availability"])),
            ("Performance", _pct(oee["performance"])),
            ("Quality", _pct(oee["quality"])),
            ("Planned time (s)", oee["planned_s"]),
            ("Run time (s)", oee["run_s"]),
            ("Downtime (s)", oee["downtime_s"]),
            ("Target rate (units/min)", oee["target_rate_per_min"] or "not set"),
        ])
        dt = oee.get("downtime_by_reason") or {}
        dt_rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{v['count']}</td>"
            f"<td>{round(v['seconds'], 1)}</td><td>{html.escape(v['component'])}</td></tr>"
            for k, v in dt.items()
        ) or "<tr><td colspan=4>no downtime recorded</td></tr>"
        oee_section = (
            f"<h2>OEE</h2><table>{oee_rows}</table>"
            f"<h3>Downtime by reason</h3><table>"
            f"<tr><th>Reason</th><th>Count</th><th>Seconds</th><th>Loss</th></tr>"
            f"{dt_rows}</table>"
        )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Batch Report {html.escape(str(summary['batch_no']))}</title>
<style>body{{font-family:sans-serif;margin:2rem;color:#222}}table{{border-collapse:collapse;margin:.5rem 0 1.5rem}}
td,th{{border:1px solid #ccc;padding:4px 12px;text-align:left}}h1{{font-size:1.3rem}}
.sig{{margin-top:2rem;padding:1rem;border:1px solid #444;background:#fafafa}}
.ok{{color:#1a7f37;font-weight:bold}}.bad{{color:#c22;font-weight:bold}}
.note{{color:#888;font-size:.8rem;margin-top:1rem}}</style></head>
<body>
<h1>Batch Inspection Report &mdash; {html.escape(str(summary['batch_no']))}</h1>
<table>{overview}</table>
{recon_section}
{oee_section}
<h2>Rejects by lane</h2><table><tr><th>Lane</th><th>Count</th></tr>{count_table(summary['rejects_by_lane'], 'rejects')}</table>
<h2>Defects by tool (Pareto)</h2><table><tr><th>Tool</th><th>Count</th></tr>{count_table(summary['defects_by_tool'], 'defects')}</table>
{images_html}
<div class="sig">{html.escape(signature_line) if signature_line else 'Not yet released.'}</div>
<p class="note">Code grades are approximate process-control indicators, NOT certified ISO 15415/15416 verifier grades.</p>
</body></html>"""
