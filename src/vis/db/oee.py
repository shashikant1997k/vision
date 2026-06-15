"""OEE (Overall Equipment Effectiveness) + downtime tracking — docs/15.

OEE = Availability × Performance × Quality
  Availability = Run_Time / Planned_Production_Time
  Performance  = (Ideal_Cycle_Time × Total_Count) / Run_Time
  Quality      = Good_Count / Total_Count

Downtime is captured as classified events using the "Six Big Losses" taxonomy
with dedicated VISION-aware reason codes (false-reject / camera micro-stop),
which legacy OEE tools dump into generic "speed loss" and lose the root cause.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from .models import Batch, DowntimeEvent, InspectionResult

# Six Big Losses reason catalogue: code -> (label, oee_component)
REASON_CODES: dict[str, tuple[str, str]] = {
    # availability (breakdowns, setup)
    "BREAKDOWN_CAMERA": ("Camera / vision hardware fault", "availability"),
    "BREAKDOWN_CONVEYOR": ("Conveyor / mechanical fault", "availability"),
    "BREAKDOWN_EJECTOR": ("Reject ejector fault", "availability"),
    "PLC_COMMS_LOSS": ("PLC / comms loss", "availability"),
    "CHANGEOVER": ("Format / recipe changeover", "availability"),
    "LINE_CLEARANCE": ("Line clearance", "availability"),
    "CHALLENGE_TEST": ("Challenge test", "availability"),
    "MAINTENANCE": ("Planned maintenance", "availability"),
    # performance (minor stops, reduced speed)
    "BLISTER_JAM": ("Blister / product jam", "performance"),
    "FEEDER_ERROR": ("Feeder / infeed error", "performance"),
    "VISION_MICROSTOP": ("Vision micro-stop (false reject / camera latency)", "performance"),
    "REDUCED_SPEED": ("Reduced speed / line imbalance", "performance"),
    # quality (handled via good/total, listed for manual entry)
    "STARTUP_REJECTS": ("Startup / adjustment rejects", "quality"),
    "OTHER": ("Other (see note)", "availability"),
}


def _parse(ts: str | None):
    return datetime.fromisoformat(ts) if ts else None


def _now():
    return datetime.now(timezone.utc)


class OEEService:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def open_downtime(self, batch_id: int | None, station: str | None = None) -> int:
        """Open a downtime event (line stopped); classify it later with close/
        reclassify. Returns the event id."""
        with self._sf() as s:
            event = DowntimeEvent(batch_id=batch_id, station=station)
            s.add(event)
            s.commit()
            return event.id

    def close_downtime(self, event_id: int, reason_code: str | None = None,
                       note: str = "", operator_id: int | None = None) -> float:
        """Close a downtime event, set its reason, and compute duration."""
        with self._sf() as s:
            event = s.get(DowntimeEvent, event_id)
            if event is None or event.ended_at is not None:
                return 0.0
            now = _now()
            event.ended_at = now.isoformat()
            started = _parse(event.started_at) or now
            event.duration_s = max(0.0, (now - started).total_seconds())
            if reason_code:
                event.reason_code = reason_code
                event.oee_component = REASON_CODES.get(reason_code, ("", "availability"))[1]
            event.note = note
            event.operator_id = operator_id
            s.commit()
            return event.duration_s

    def log_downtime(self, batch_id, reason_code, duration_s, *, station=None,
                     note="", operator_id=None) -> int:
        """Record a complete downtime event in one call (known duration)."""
        with self._sf() as s:
            now = _now()
            event = DowntimeEvent(
                batch_id=batch_id, station=station, reason_code=reason_code,
                oee_component=REASON_CODES.get(reason_code, ("", "availability"))[1],
                note=note, operator_id=operator_id, duration_s=float(duration_s),
                started_at=now.isoformat(), ended_at=now.isoformat(),
            )
            s.add(event)
            s.commit()
            return event.id

    def set_target_rate(self, batch_id: int, units_per_min: float) -> None:
        with self._sf() as s:
            batch = s.get(Batch, batch_id)
            if batch is not None:
                data = dict(batch.oee_data or {})
                data["target_rate_per_min"] = float(units_per_min)
                batch.oee_data = data
                s.commit()

    def compute(self, batch_id: int) -> dict:
        with self._sf() as s:
            return compute_oee(s, batch_id)


def compute_oee(session, batch_id: int) -> dict:
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

    downtimes = session.execute(
        select(DowntimeEvent).where(DowntimeEvent.batch_id == batch_id)
    ).scalars().all()
    downtime_s = sum(d.duration_s or 0.0 for d in downtimes)
    by_reason: dict[str, dict] = {}
    for d in downtimes:
        code = d.reason_code or "UNCLASSIFIED"
        entry = by_reason.setdefault(code, {"count": 0, "seconds": 0.0,
                                            "component": d.oee_component})
        entry["count"] += 1
        entry["seconds"] += d.duration_s or 0.0

    start = _parse(batch.started_at)
    end = _parse(batch.closed_at) or _now()
    planned_s = max(0.0, (end - start).total_seconds()) if start else 0.0
    run_s = max(0.0, planned_s - downtime_s)

    target_rate = float((batch.oee_data or {}).get("target_rate_per_min") or 0.0)
    ideal_cycle_s = 60.0 / target_rate if target_rate else 0.0

    availability = (run_s / planned_s) if planned_s else 0.0
    performance = (
        (ideal_cycle_s * total) / run_s if (run_s and ideal_cycle_s) else 0.0
    )
    performance = min(performance, 1.0)  # cap (clock granularity / over-speed)
    quality = (good / total) if total else 0.0
    oee = availability * performance * quality

    return {
        "total": total,
        "good": good,
        "planned_s": round(planned_s, 1),
        "downtime_s": round(downtime_s, 1),
        "run_s": round(run_s, 1),
        "target_rate_per_min": target_rate,
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "oee": round(oee, 4),
        "downtime_by_reason": dict(
            sorted(by_reason.items(), key=lambda kv: -kv[1]["seconds"])
        ),
    }
