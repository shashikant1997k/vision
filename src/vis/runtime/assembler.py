from __future__ import annotations

from ..common.events import EventBus
from ..db.audit import AuditService
from ..db.models import CameraAssignment
from ..db.stations import StationRepository
from ..db.store import ResultStore
from ..io import RejectController, SimulatedIO
from .runner import InspectionRunner


def default_sim_factory(camera_id, settings, recipe):
    """Dev/test camera source: a simulated code line. Production swaps in a
    factory that builds HarvesterCamera(camera_id, settings=settings, ...)."""
    from ..engine.sim import SimulatedCodeCamera

    return SimulatedCodeCamera(camera_id, recipe, num_frames=4, defect_rate=0.3, seed=0)


class RuntimeAssembler:
    """Builds a live InspectionRunner from persisted station configuration.

    Persisted reject outputs build the RejectController; persisted camera
    settings configure each source via a camera_factory; results are bound to
    the batch and camera↔recipe assignments are recorded. This is the
    "load station → run batch" glue.
    """

    def __init__(self, session_factory, camera_factory=default_sim_factory, reject_io=None) -> None:
        self._sf = session_factory
        self._repo = StationRepository(session_factory)
        self._camera_factory = camera_factory
        self._reject_io = reject_io or SimulatedIO()

    def build_runner(
        self,
        station_id: int,
        assignments,  # list[(camera_name, recipe)]
        pool,
        *,
        bus: EventBus | None = None,
        batch_id: int | None = None,
        stats=None,
        live_view=None,
        on_frame=None,
        user_id: int | None = None,
    ) -> InspectionRunner:
        bus = bus or EventBus()
        reject_handler = RejectController(
            self._repo.reject_output_configs(station_id), io=self._reject_io
        )
        cameras_by_name = {
            name: (cam_id, settings) for cam_id, name, settings in self._repo.cameras(station_id)
        }

        runtime_assignments = []
        for camera_name, recipe in assignments:
            entry = cameras_by_name.get(camera_name)
            settings = entry[1] if entry else None
            source = self._camera_factory(camera_name, settings, recipe)
            runtime_assignments.append((source, recipe))
            if batch_id is not None and entry is not None:
                self._record_assignment(batch_id, entry[0], recipe, user_id)

        if batch_id is not None:
            bus.subscribe(
                "inspection.result", ResultStore(self._sf, batch_id=batch_id).on_result
            )

        return InspectionRunner(
            runtime_assignments,
            pool,
            bus=bus,
            stats=stats,
            live_view=live_view,
            reject_handler=reject_handler,
            on_frame=on_frame,
        )

    def _record_assignment(self, batch_id, camera_db_id, recipe, user_id) -> None:
        with self._sf() as s:
            s.add(
                CameraAssignment(
                    batch_id=batch_id,
                    camera_id=camera_db_id,
                    recipe_ref=getattr(recipe, "recipe_id", "?"),
                    recipe_version=getattr(recipe, "version", None),
                )
            )
            AuditService(s).record(
                "camera.assign",
                "camera_assignment",
                camera_db_id,
                user_id=user_id,
                after={"batch_id": batch_id, "recipe": getattr(recipe, "recipe_id", "?")},
            )
            s.commit()
