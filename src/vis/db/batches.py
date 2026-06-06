from __future__ import annotations

from datetime import datetime, timezone

from ..security.authz import Perm, require
from .audit import AuditService
from .models import Batch, ESignature, Recipe
from .users import AuthError, verify_user


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchService:
    """Batch lifecycle: start (against an approved recipe) and close (batch
    release with a two-component electronic signature)."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def start(
        self,
        recipe_id: int,
        batch_no: str,
        user_id: int,
        *,
        mfg_date: str | None = None,
        exp_date: str | None = None,
        mrp: str | None = None,
        variable_data: dict | None = None,
    ) -> int:
        with self._sf() as s:
            require(s, user_id, Perm.BATCH_MANAGE)
            recipe = s.get(Recipe, recipe_id)
            if recipe is None:
                raise ValueError(f"recipe {recipe_id} not found")
            if recipe.status != "approved":
                raise ValueError("recipe must be approved before a batch can start")

            batch = Batch(
                product_id=recipe.product_id,
                recipe_id=recipe.id,
                recipe_version=recipe.version,
                batch_no=batch_no,
                mfg_date=mfg_date,
                exp_date=exp_date,
                mrp=mrp,
                variable_data=variable_data or {},
                status="open",
                started_by=user_id,
                started_at=_now(),
            )
            s.add(batch)
            s.flush()
            AuditService(s).record(
                "batch.start",
                "batch",
                batch.id,
                user_id=user_id,
                after={"batch_no": batch_no, "recipe_id": recipe_id, "status": "open"},
            )
            s.commit()
            return batch.id

    def close(
        self, batch_id: int, user_id: int, password: str, meaning: str = "Batch released"
    ) -> int:
        """Close (release) a batch. Requires batch.manage AND password re-entry
        (two-component e-signature). Returns the signature id."""
        with self._sf() as s:
            require(s, user_id, Perm.BATCH_MANAGE)
            if not verify_user(s, user_id, password):
                raise AuthError("electronic signature failed: invalid password")
            batch = s.get(Batch, batch_id)
            if batch is None:
                raise ValueError(f"batch {batch_id} not found")
            if batch.status == "closed":
                raise ValueError("batch already closed")

            signature = ESignature(
                user_id=user_id, meaning=meaning, entity_type="batch", entity_id=str(batch_id)
            )
            s.add(signature)
            s.flush()
            batch.status = "closed"
            batch.closed_at = _now()
            AuditService(s).record(
                "batch.close",
                "batch",
                batch_id,
                user_id=user_id,
                before={"status": "open"},
                after={"status": "closed"},
                signature_id=signature.id,
            )
            s.commit()
            return signature.id
