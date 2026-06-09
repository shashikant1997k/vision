from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from .models import AuditEntry

GENESIS = "0" * 64


def _canonical(ts, user_id, action, entity_type, entity_id, before, after, prev_hash) -> str:
    return json.dumps(
        {
            "ts": ts,
            "user_id": user_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "before": before,
            "after": after,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(*args) -> str:
    return hashlib.sha256(_canonical(*args).encode("utf-8")).hexdigest()


class AuditService:
    """Append-only, hash-chained audit trail (21 CFR 11.10(e)).

    Each entry's hash covers its content plus the previous entry's hash, so any
    modification, reordering, or deletion breaks the chain and is detectable via
    verify_chain(). The app only ever inserts; on PostgreSQL, also REVOKE
    UPDATE, DELETE on this table from the application role (D-013) so the
    append-only guarantee is enforced by the database, not just the code.
    """

    def __init__(self, session) -> None:
        self.session = session

    def list_entries(self, limit: int = 300) -> list[dict]:
        """Recent audit entries (newest first) for the log viewer."""
        from .models import User

        rows = self.session.execute(
            select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)
        ).scalars().all()
        out = []
        for e in rows:
            user = self.session.get(User, e.user_id) if e.user_id else None
            out.append({
                "id": e.id, "ts": e.ts, "user": user.username if user else "—",
                "action": e.action, "entity": f"{e.entity_type}#{e.entity_id}",
                "signed": e.signature_id is not None,
            })
        return out

    def record(
        self,
        action: str,
        entity_type: str,
        entity_id,
        *,
        user_id: int | None = None,
        before: dict | None = None,
        after: dict | None = None,
        signature_id: int | None = None,
    ) -> AuditEntry:
        last = self.session.execute(
            select(AuditEntry).order_by(AuditEntry.id.desc()).limit(1)
        ).scalars().first()
        prev_hash = last.entry_hash if last else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        entry_hash = _hash(ts, user_id, action, entity_type, entity_id, before, after, prev_hash)
        entry = AuditEntry(
            ts=ts,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=before,
            after=after,
            signature_id=signature_id,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self.session.add(entry)
        self.session.flush()
        return entry

    def verify_chain(self) -> tuple[bool, int | None]:
        """Return (ok, first_broken_id). ok=True means the whole chain is intact."""
        prev_hash = GENESIS
        for e in self.session.execute(select(AuditEntry).order_by(AuditEntry.id.asc())).scalars():
            expected = _hash(
                e.ts, e.user_id, e.action, e.entity_type, e.entity_id, e.before, e.after, prev_hash
            )
            if e.prev_hash != prev_hash or e.entry_hash != expected:
                return False, e.id
            prev_hash = e.entry_hash
        return True, None
