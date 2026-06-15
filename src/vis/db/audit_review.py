"""Audit-trail review by exception (docs/16) — the #1 GxP inspection finding.

Regulators expect a qualified, independent reviewer to review the audit trail
BEFORE batch disposition, focused on CRITICAL/anomalous entries rather than
every line (PIC/S PI 041 "exception report"; MHRA; FDA 211.22). This module:

- classifies audit entries into a versioned anomaly taxonomy (critical/major/
  minor) — the "validated exception report",
- records the review as an attributable, e-signed, hash-chained record,
- tracks an incremental watermark (last audit-entry id reviewed),
- enforces segregation of duties (reviewer must not be a performer in the
  window) and verify_chain() integrity,
- gates batch release on unreviewed CRITICAL anomalies.
"""

from __future__ import annotations

from sqlalchemy import select

from ..security.authz import Perm, require
from .audit import AuditService
from .models import AuditEntry, AuditReview, ESignature
from .users import AuthError, verify_user

RULESET_VERSION = "v1"

CRITICAL, MAJOR, MINOR = "critical", "major", "minor"


def classify(entry: AuditEntry) -> tuple[str, str] | None:
    """Map an audit entry to (code, severity), or None if not noteworthy.
    The versioned exception ruleset — the documented review criteria."""
    action = entry.action or ""
    after = entry.after or {}

    # CRITICAL — the literal inspection findings
    if action == "time.anomaly":
        return ("CLOCK_CHANGE", CRITICAL)
    if action in ("audit.disable", "record.void", "record.delete"):
        return ("RECORD_VOID_OR_AUDIT_OFF", CRITICAL)
    if action == "batch.close" and after.get("override_reason"):
        return ("RECONCILIATION_OVERRIDE", CRITICAL)
    if action == "challenge.run" and after.get("result") == "fail":
        return ("CHALLENGE_TEST_FAILED", CRITICAL)
    if action == "result.override":
        return ("RESULT_OVERRIDE", CRITICAL)

    # MAJOR — must be acknowledged
    if action.startswith("recipe.") and action != "recipe.draft":
        return ("RECIPE_CHANGE", MAJOR)
    if action.startswith("user.") or action.startswith("role."):
        return ("USER_OR_ROLE_CHANGE", MAJOR)
    if action == "auth.lockout":
        return ("ACCOUNT_LOCKOUT", MAJOR)

    # MINOR — informational, auto-acknowledged
    if action.startswith(("font.", "batch.reconcile", "station.")):
        return ("CONFIG_CHANGE", MINOR)
    return None


def _severity_rank(sev: str) -> int:
    return {CRITICAL: 3, MAJOR: 2, MINOR: 1}.get(sev, 0)


class AuditReviewService:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def watermark(self, batch_id: int | None) -> int:
        """Highest audit-entry id already reviewed for this scope (0 if none)."""
        with self._sf() as s:
            row = s.execute(
                select(AuditReview).where(
                    AuditReview.batch_id == batch_id,
                    AuditReview.outcome != "rejected",
                ).order_by(AuditReview.reviewed_to_id.desc())
            ).scalars().first()
            return row.reviewed_to_id if row else 0

    def _batch_start_id(self, s, batch_id: int) -> int:
        """The audit-entry id of this batch's start — the natural lower bound of
        the batch review window (so pre-batch activity isn't attributed here)."""
        row = s.execute(
            select(AuditEntry).where(
                AuditEntry.action == "batch.start",
                AuditEntry.entity_type == "batch",
                AuditEntry.entity_id == str(batch_id),
            ).order_by(AuditEntry.id.asc())
        ).scalars().first()
        return (row.id - 1) if row else 0

    def pending(self, batch_id: int | None = None) -> dict:
        """Audit entries above the watermark, with their anomaly flags. For a
        batch, the window starts at the batch's own start entry (so pre-batch
        activity is excluded)."""
        with self._sf() as s:
            low = self.watermark(batch_id)
            if batch_id is not None:
                low = max(low, self._batch_start_id(s, batch_id))
            query = select(AuditEntry).where(AuditEntry.id > low).order_by(AuditEntry.id.asc())
            if batch_id is not None:
                # entries referencing this batch + global anomalies (time/user)
                entries = [
                    e for e in s.execute(query).scalars()
                    if (e.entity_type == "batch" and e.entity_id == str(batch_id))
                    or classify(e) is not None
                ]
            else:
                entries = list(s.execute(query).scalars())
            flags = []
            for e in entries:
                hit = classify(e)
                if hit is None:
                    continue
                code, severity = hit
                flags.append({
                    "audit_id": e.id, "action": e.action, "ts": e.ts,
                    "user_id": e.user_id, "code": code, "severity": severity,
                })
            high = max((e.id for e in entries), default=low)
            return {
                "from_id": low, "to_id": high,
                "entries_total": len(entries),
                "flags": flags,
                "critical": [f for f in flags if f["severity"] == CRITICAL],
            }

    def unreviewed_critical(self, batch_id: int) -> list[dict]:
        return self.pending(batch_id)["critical"]

    def _performers_in_window(self, s, low: int, high: int) -> set[int]:
        rows = s.execute(
            select(AuditEntry.user_id).where(
                AuditEntry.id > low, AuditEntry.id <= high, AuditEntry.user_id.is_not(None)
            )
        ).scalars()
        return {uid for uid in rows}

    def review(
        self, reviewer_id: int, password: str, batch_id: int | None,
        dispositions: dict | None = None, outcome: str = "accepted",
    ) -> dict:
        """Record an e-signed audit-trail review over the pending window.

        Enforces: valid e-signature, chain integrity, segregation of duties
        (reviewer must not have performed any action in the window), and that
        every CRITICAL flag has a disposition comment. Returns the review."""
        dispositions = dispositions or {}
        with self._sf() as s:
            require(s, reviewer_id, Perm.AUDIT_VIEW)
            if not verify_user(s, reviewer_id, password):
                raise AuthError("electronic signature failed: invalid password")

            pending = self.pending(batch_id)
            low, high = pending["from_id"], pending["to_id"]

            # segregation of duties: independent reviewer
            performers = self._performers_in_window(s, low, high)
            if reviewer_id in performers:
                raise ValueError(
                    "segregation of duties: the reviewer performed actions in this "
                    "window and cannot review their own work"
                )

            # chain integrity over everything up to the window end
            chain_ok, _broken = AuditService(s).verify_chain()
            if not chain_ok:
                raise ValueError("audit chain integrity check FAILED — do not release")

            # every CRITICAL flag needs a disposition comment
            missing = [
                f["audit_id"] for f in pending["critical"]
                if not (dispositions.get(str(f["audit_id"])) or "").strip()
            ]
            if missing:
                raise ValueError(
                    f"{len(missing)} critical anomaly(ies) need a disposition comment "
                    f"before sign-off: audit ids {missing}"
                )

            flags = pending["flags"]
            for f in flags:
                comment = dispositions.get(str(f["audit_id"]))
                if comment:
                    f["disposition"] = comment

            signature = ESignature(
                user_id=reviewer_id, meaning="Audit trail reviewed",
                entity_type="audit_review", entity_id=str(batch_id or "period"),
            )
            s.add(signature)
            s.flush()
            review = AuditReview(
                batch_id=batch_id, scope="batch" if batch_id else "period",
                reviewed_from_id=low, reviewed_to_id=high,
                entries_total=pending["entries_total"], entries_flagged=len(flags),
                chain_verified=chain_ok, flags=flags, outcome=outcome,
                reviewer_id=reviewer_id, signature_id=signature.id,
                ruleset_version=RULESET_VERSION,
            )
            s.add(review)
            s.flush()
            AuditService(s).record(
                "audit.review", "audit_review", review.id, user_id=reviewer_id,
                after={"batch_id": batch_id, "to_id": high, "flagged": len(flags),
                       "outcome": outcome},
                signature_id=signature.id,
            )
            s.commit()
            return {"id": review.id, "reviewed_to_id": high,
                    "entries_total": pending["entries_total"], "flagged": len(flags)}

    def list_reviews(self, limit: int = 100) -> list[dict]:
        with self._sf() as s:
            rows = s.execute(
                select(AuditReview).order_by(AuditReview.id.desc()).limit(limit)
            ).scalars()
            return [{
                "id": r.id, "batch_id": r.batch_id, "outcome": r.outcome,
                "reviewed_to_id": r.reviewed_to_id, "entries_flagged": r.entries_flagged,
                "chain_verified": r.chain_verified, "reviewer_id": r.reviewer_id,
                "created_at": r.created_at,
            } for r in rows]
