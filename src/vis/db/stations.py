from __future__ import annotations

from sqlalchemy import select

from ..camera.settings import CameraSettings
from ..io.reject import RejectOutputConfig
from ..security.authz import Perm, require
from .audit import AuditService
from .models import CameraRow, RejectOutputRow, Station


class StationRepository:
    """Persists station/camera/reject-output hardware config (RBAC-gated and
    audited) and bridges it to the runtime camera & I/O modules."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    # --- configuration (write; permissioned + audited) ------------------------
    def create_station(self, name: str, user_id: int, line: str = "") -> int:
        with self._sf() as s:
            require(s, user_id, Perm.STATION_MANAGE)
            station = Station(name=name, line=line)
            s.add(station)
            s.flush()
            AuditService(s).record(
                "station.create", "station", station.id, user_id=user_id,
                after={"name": name, "line": line},
            )
            s.commit()
            return station.id

    def add_camera(
        self,
        station_id: int,
        name: str,
        user_id: int,
        identifier: str = "",
        model: str = "",
        vendor: str = "",
        interface: str = "GigE Vision",
        settings: CameraSettings | None = None,
    ) -> int:
        with self._sf() as s:
            require(s, user_id, Perm.STATION_MANAGE)
            camera = CameraRow(
                station_id=station_id,
                name=name,
                identifier=identifier,
                model=model,
                vendor=vendor,
                interface=interface,
                settings=(settings or CameraSettings()).to_dict(),
            )
            s.add(camera)
            s.flush()
            AuditService(s).record(
                "camera.add", "camera", camera.id, user_id=user_id,
                after={"station_id": station_id, "name": name, "identifier": identifier},
            )
            s.commit()
            return camera.id

    def update_camera_settings(
        self, camera_id: int, settings: CameraSettings, user_id: int
    ) -> None:
        with self._sf() as s:
            require(s, user_id, Perm.STATION_MANAGE)
            camera = s.get(CameraRow, camera_id)
            if camera is None:
                raise ValueError(f"camera {camera_id} not found")
            before = camera.settings
            camera.settings = settings.to_dict()
            AuditService(s).record(
                "camera.settings", "camera", camera_id, user_id=user_id,
                before=before, after=camera.settings,
            )
            s.commit()

    def add_reject_output(
        self,
        station_id: int,
        name: str,
        channel: int,
        user_id: int,
        eject_delay_ms: int = 0,
        pulse_ms: int = 100,
    ) -> int:
        with self._sf() as s:
            require(s, user_id, Perm.STATION_MANAGE)
            row = RejectOutputRow(
                station_id=station_id,
                name=name,
                channel=channel,
                eject_delay_ms=eject_delay_ms,
                pulse_ms=pulse_ms,
            )
            s.add(row)
            s.flush()
            AuditService(s).record(
                "reject_output.add", "reject_output", row.id, user_id=user_id,
                after={"name": name, "channel": channel},
            )
            s.commit()
            return row.id

    # --- bridges to the runtime (read) ----------------------------------------
    def camera_settings(self, camera_id: int) -> CameraSettings:
        with self._sf() as s:
            camera = s.get(CameraRow, camera_id)
            if camera is None:
                raise ValueError(f"camera {camera_id} not found")
            return CameraSettings.from_dict(camera.settings)

    def cameras(self, station_id: int) -> list[tuple[int, str, CameraSettings]]:
        with self._sf() as s:
            rows = s.execute(
                select(CameraRow).where(CameraRow.station_id == station_id)
            ).scalars().all()
            return [(r.id, r.name, CameraSettings.from_dict(r.settings)) for r in rows]

    def reject_output_configs(self, station_id: int) -> list[RejectOutputConfig]:
        """Build the RejectController config straight from persisted config."""
        with self._sf() as s:
            rows = s.execute(
                select(RejectOutputRow)
                .where(RejectOutputRow.station_id == station_id)
                .order_by(RejectOutputRow.channel)
            ).scalars().all()
            return [
                RejectOutputConfig(
                    name=r.name,
                    channel=r.channel,
                    eject_delay_ms=r.eject_delay_ms,
                    pulse_ms=r.pulse_ms,
                )
                for r in rows
            ]
