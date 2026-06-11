"""Key/value application settings (JSON) + the operational event log."""

from __future__ import annotations

from sqlalchemy import select

from .models import EventRow, SettingRow


class SettingsService:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def get(self, key: str, default=None):
        with self._sf() as s:
            row = s.execute(select(SettingRow).where(SettingRow.key == key)).scalars().first()
            return row.value if row is not None else default

    def set(self, key: str, value) -> None:
        with self._sf() as s:
            row = s.execute(select(SettingRow).where(SettingRow.key == key)).scalars().first()
            if row is None:
                s.add(SettingRow(key=key, value=value))
            else:
                row.value = value
            s.commit()


class EventService:
    """Operational events/alarms (run, stop, alarm raised/cleared, batch open/
    close). Append-only; read by the Events screen and exported with reports."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def log(self, severity: str, source: str, message: str, batch_id: int | None = None) -> int:
        with self._sf() as s:
            row = EventRow(severity=severity, source=source, message=message, batch_id=batch_id)
            s.add(row)
            s.commit()
            return row.id

    def list_events(self, limit: int = 300, severity: str | None = None) -> list[dict]:
        with self._sf() as s:
            query = select(EventRow).order_by(EventRow.id.desc()).limit(limit)
            if severity:
                query = query.where(EventRow.severity == severity)
            return [
                {"id": e.id, "ts": e.ts, "severity": e.severity,
                 "source": e.source, "message": e.message, "batch_id": e.batch_id}
                for e in s.execute(query).scalars()
            ]
