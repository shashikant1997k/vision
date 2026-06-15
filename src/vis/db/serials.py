"""Serial registry — per-batch serial uniqueness, duplicate detection, and the
data the reconciliation engine needs (docs/13).

A serial must be unique within a batch (EU FMD / US DSCSA). The first sighting
is registered NEW; any later sighting of the same serial in the same batch is a
DUPLICATE — the signal of a printer double-fire, a reprint, or counterfeit
re-injection. Duplicate sightings are counted and surfaced as a data-integrity
event; the unit is also a quality reject.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func, select

from .models import SerialRecord


class SerialStatus(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"


@dataclass
class SerialOutcome:
    status: SerialStatus
    serial: str
    seen_count: int


class SerialRegistry:
    """Thread-safe per-batch serial uniqueness. DB-backed (survives restarts
    mid-batch) with an in-memory fast path. Bind to a batch with `for_batch`."""

    def __init__(self, session_factory, batch_id: int | None) -> None:
        self._sf = session_factory
        self._batch_id = batch_id
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        if session_factory is not None and batch_id is not None:
            with session_factory() as s:
                rows = s.execute(
                    select(SerialRecord.serial).where(SerialRecord.batch_id == batch_id)
                ).scalars()
                self._seen = set(rows)

    def check_and_register(
        self, serial: str, gtin: str | None = None, camera_id: str | None = None,
        frame_id: int | None = None,
    ) -> SerialOutcome:
        """Register a serial. NEW on first sight; DUPLICATE on any later sight
        within the batch (the duplicate's seen_count is incremented)."""
        serial = (serial or "").strip()
        if not serial:
            return SerialOutcome(SerialStatus.NEW, serial, 0)
        with self._lock:
            duplicate = serial in self._seen
            self._seen.add(serial)
            if self._sf is None or self._batch_id is None:
                return SerialOutcome(
                    SerialStatus.DUPLICATE if duplicate else SerialStatus.NEW, serial,
                    2 if duplicate else 1,
                )
            with self._sf() as s:
                row = s.execute(
                    select(SerialRecord).where(
                        SerialRecord.batch_id == self._batch_id, SerialRecord.serial == serial
                    )
                ).scalars().first()
                if row is None:
                    row = SerialRecord(
                        batch_id=self._batch_id, serial=serial, gtin=gtin,
                        status="good", camera_id=camera_id, first_frame=frame_id, seen_count=1,
                    )
                    s.add(row)
                    s.commit()
                    return SerialOutcome(SerialStatus.NEW, serial, 1)
                row.seen_count += 1
                row.status = "duplicate"
                s.commit()
                return SerialOutcome(SerialStatus.DUPLICATE, serial, row.seen_count)

    def mark_status(self, serial: str, status: str) -> None:
        """Set a serial's reconciliation status (good/rejected)."""
        if self._sf is None or self._batch_id is None:
            return
        with self._sf() as s:
            row = s.execute(
                select(SerialRecord).where(
                    SerialRecord.batch_id == self._batch_id, SerialRecord.serial == serial
                )
            ).scalars().first()
            if row is not None and row.status != "duplicate":
                row.status = status
                s.commit()

    def summary(self) -> dict:
        """Counts for reconciliation: unique serials, duplicates, by status."""
        if self._sf is None or self._batch_id is None:
            return {"unique": len(self._seen), "duplicates": 0, "duplicate_serials": []}
        with self._sf() as s:
            unique = s.execute(
                select(func.count()).select_from(SerialRecord).where(
                    SerialRecord.batch_id == self._batch_id
                )
            ).scalar()
            dup_rows = s.execute(
                select(SerialRecord).where(
                    SerialRecord.batch_id == self._batch_id,
                    SerialRecord.seen_count > 1,
                )
            ).scalars().all()
            return {
                "unique": int(unique or 0),
                "duplicates": len(dup_rows),
                "duplicate_serials": [
                    {"serial": r.serial, "seen_count": r.seen_count} for r in dup_rows
                ],
            }
