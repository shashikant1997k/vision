"""Batch reconciliation — the regulated accounting that proves no mix-up or
unexplained loss (docs/13, GMP line-clearance & reconciliation).

Compares units IN (issued) against everything OUT — good accepted, rejected,
samples removed, recovered/reworked, destroyed — computes yield and
reconciliation %, and flags whether the unaccounted balance is within tolerance.
Inspection counts (good/rejected) come from the inspection results; the operator
enters issued/samples/recovered/destroyed and the physical reject-bin count.
"""

from __future__ import annotations

from sqlalchemy import func, select

from ..security.authz import Perm, require
from .audit import AuditService
from .models import Batch, InspectionResult, SerialRecord

# operator-entered figures and their defaults
RECON_FIELDS = ("units_in", "samples_removed", "recovered", "destroyed", "reject_bin_count")
DEFAULT_TOLERANCE_PCT = 0.5


def compute_reconciliation(session, batch_id: int) -> dict:
    """Full reconciliation for a batch. Inspection figures are authoritative for
    good/rejected; operator figures fill issued/samples/recovered/destroyed."""
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise ValueError(f"batch {batch_id} not found")

    total = session.execute(
        select(func.count()).select_from(InspectionResult).where(
            InspectionResult.batch_id == batch_id
        )
    ).scalar() or 0
    good = session.execute(
        select(func.count()).select_from(InspectionResult).where(
            InspectionResult.batch_id == batch_id, InspectionResult.passed.is_(True)
        )
    ).scalar() or 0
    rejected = total - good

    dup_rows = session.execute(
        select(SerialRecord).where(
            SerialRecord.batch_id == batch_id, SerialRecord.seen_count > 1
        )
    ).scalars().all()
    unique_serials = session.execute(
        select(func.count()).select_from(SerialRecord).where(
            SerialRecord.batch_id == batch_id
        )
    ).scalar() or 0

    recon = dict(batch.recon_data or {})
    units_in = int(recon.get("units_in") or 0)
    samples = int(recon.get("samples_removed") or 0)
    recovered = int(recon.get("recovered") or 0)
    destroyed = int(recon.get("destroyed") or 0)
    reject_bin = recon.get("reject_bin_count")
    tolerance = float(recon.get("tolerance_pct", DEFAULT_TOLERANCE_PCT))

    # accounted output: good + rejected + samples + destroyed (recovered units
    # re-enter the good stream, so they are not added again)
    accounted = good + rejected + samples + destroyed
    unaccounted = units_in - accounted if units_in else 0
    yield_pct = round(100 * good / units_in, 2) if units_in else (
        round(100 * good / total, 2) if total else 0.0
    )
    recon_pct = round(100 * accounted / units_in, 2) if units_in else None
    within_tolerance = (
        abs(100 - recon_pct) <= tolerance if recon_pct is not None else None
    )
    # reject-bin physical count vs system rejected count
    bin_delta = (int(reject_bin) - rejected) if reject_bin not in (None, "") else None

    return {
        "batch_no": batch.batch_no,
        "units_in": units_in,
        "total_inspected": total,
        "good": good,
        "rejected": rejected,
        "samples_removed": samples,
        "recovered": recovered,
        "destroyed": destroyed,
        "accounted": accounted,
        "unaccounted": unaccounted,
        "yield_pct": yield_pct,
        "reconciliation_pct": recon_pct,
        "tolerance_pct": tolerance,
        "within_tolerance": within_tolerance,
        "reject_bin_count": int(reject_bin) if reject_bin not in (None, "") else None,
        "reject_bin_delta": bin_delta,
        "unique_serials": int(unique_serials),
        "duplicate_serials": [
            {"serial": r.serial, "seen_count": r.seen_count} for r in dup_rows
        ],
        "reconciled": bool(units_in) and within_tolerance and not dup_rows,
    }


class ReconciliationService:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def set_figures(self, batch_id: int, user_id: int, figures: dict) -> dict:
        """Store the operator-entered reconciliation figures (audited) and
        return the recomputed reconciliation."""
        with self._sf() as s:
            require(s, user_id, Perm.BATCH_MANAGE)
            batch = s.get(Batch, batch_id)
            if batch is None:
                raise ValueError(f"batch {batch_id} not found")
            data = dict(batch.recon_data or {})
            for key in (*RECON_FIELDS, "tolerance_pct"):
                if key in figures and figures[key] not in (None, ""):
                    data[key] = figures[key]
            batch.recon_data = data
            AuditService(s).record(
                "batch.reconcile", "batch", batch_id, user_id=user_id, after=data
            )
            s.commit()
            return compute_reconciliation(s, batch_id)

    def compute(self, batch_id: int) -> dict:
        with self._sf() as s:
            return compute_reconciliation(s, batch_id)
