"""Challenge-test (known-bad sample verification) service — docs/14.

A challenge test proves the running system DETECTS and physically REJECTS seeded
defects. It is an in-process GMP control run at line/batch/shift start, after
breaks, changeover and maintenance. Each test records its shots (expected vs
actual verdict + 24V reject confirmation), is e-signed by the operator, and
GATES the line: a passing test unlocks production; a failing one blocks it and
raises a deviation. Legacy systems leave this on paper — here it is a controlled
electronic record linked to the recipe version and batch.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from ..security.authz import Perm, require
from .audit import AuditService
from .models import (
    ChallengeShot,
    ChallengeTest,
    DefectLibraryItem,
    ESignature,
    Recipe,
)
from .users import AuthError, verify_user

TRIGGERS = (
    "line_start", "batch_start", "shift_start", "shift_end",
    "after_break", "after_changeover", "after_maintenance", "periodic",
)

# starter defect catalogue (seeded once) — the canonical pharma-coding failures
STARTER_DEFECTS = [
    ("NO_CODE", "missing", "No code / blank print"),
    ("WRONG_GTIN", "mismatch", "Wrong GTIN (different product)"),
    ("EXPIRED", "mismatch", "Expired / wrong expiry date"),
    ("DUP_SERIAL", "duplicate", "Duplicate serial number"),
    ("LOW_GRADE", "quality", "Unreadable / low-grade code"),
    ("WRONG_TEXT", "mismatch", "Wrong lot / human-readable text"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChallengeService:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    # ---- defect library ---------------------------------------------------
    def ensure_starter_defects(self) -> None:
        with self._sf() as s:
            existing = {d.code for d in s.execute(select(DefectLibraryItem)).scalars()}
            for code, klass, desc in STARTER_DEFECTS:
                if code not in existing:
                    s.add(DefectLibraryItem(code=code, defect_class=klass, description=desc))
            s.commit()

    def list_defects(self, active_only: bool = True) -> list[dict]:
        with self._sf() as s:
            query = select(DefectLibraryItem).order_by(DefectLibraryItem.code)
            if active_only:
                query = query.where(DefectLibraryItem.active.is_(True))
            return [
                {"id": d.id, "code": d.code, "defect_class": d.defect_class,
                 "description": d.description, "expected_verdict": d.expected_verdict}
                for d in s.execute(query).scalars()
            ]

    def add_defect(self, user_id: int, code: str, defect_class: str, description: str,
                   expected_verdict: str = "reject") -> int:
        with self._sf() as s:
            require(s, user_id, Perm.STATION_MANAGE)
            item = DefectLibraryItem(
                code=code, defect_class=defect_class, description=description,
                expected_verdict=expected_verdict,
            )
            s.add(item)
            s.flush()
            AuditService(s).record("challenge.defect_add", "defect", item.id,
                                    user_id=user_id, after={"code": code})
            s.commit()
            return item.id

    # ---- running a test ---------------------------------------------------
    def run_test(
        self, user_id: int, password: str, trigger_reason: str, shots: list[dict],
        *, recipe_id: int | None = None, batch_id: int | None = None,
        station: str | None = None, supervisor_id: int | None = None,
    ) -> dict:
        """Record a completed challenge test in one transaction and e-sign it.

        `shots` = [{defect_item_id?, label, expected_verdict, actual_verdict,
        reject_io_confirmed}]. A shot passes when actual == expected AND, for an
        expected-reject shot, the 24V reject actuator confirmed. The test passes
        only if every shot passes. Returns the result dict; raises on bad e-sig."""
        if trigger_reason not in TRIGGERS:
            raise ValueError(f"unknown trigger {trigger_reason!r}")
        if not shots:
            raise ValueError("a challenge test needs at least one shot")
        with self._sf() as s:
            require(s, user_id, Perm.BATCH_MANAGE)
            if not verify_user(s, user_id, password):
                raise AuthError("electronic signature failed: invalid password")
            recipe_version = None
            if recipe_id is not None:
                recipe = s.get(Recipe, recipe_id)
                recipe_version = recipe.version if recipe else None

            test = ChallengeTest(
                trigger_reason=trigger_reason, batch_id=batch_id, recipe_id=recipe_id,
                recipe_version=recipe_version, station=station, operator_id=user_id,
                supervisor_id=supervisor_id, result="pending", started_at=_now(),
            )
            s.add(test)
            s.flush()

            all_pass = True
            for shot in shots:
                expected = shot.get("expected_verdict", "reject")
                actual = shot.get("actual_verdict", "")
                io_ok = bool(shot.get("reject_io_confirmed", False))
                shot_pass = actual == expected and (expected != "reject" or io_ok)
                all_pass = all_pass and shot_pass
                s.add(ChallengeShot(
                    test_id=test.id, defect_item_id=shot.get("defect_item_id"),
                    label=shot.get("label", ""), expected_verdict=expected,
                    actual_verdict=actual, reject_io_confirmed=io_ok,
                    passed=shot_pass, detail=shot.get("detail") or {},
                ))

            signature = ESignature(
                user_id=user_id, meaning=f"challenge test ({trigger_reason})",
                entity_type="challenge_test", entity_id=str(test.id),
            )
            s.add(signature)
            s.flush()
            test.result = "pass" if all_pass else "fail"
            test.line_gate_action = "unlocked" if all_pass else "blocked"
            test.completed_at = _now()
            test.signature_id = signature.id
            AuditService(s).record(
                "challenge.run", "challenge_test", test.id, user_id=user_id,
                after={"trigger": trigger_reason, "result": test.result,
                       "gate": test.line_gate_action},
                signature_id=signature.id,
            )
            s.commit()
            return {"id": test.id, "result": test.result,
                    "line_gate_action": test.line_gate_action}

    # ---- queries / line-start gate ---------------------------------------
    def latest_pass(self, recipe_id: int | None = None, within_hours: float | None = None):
        """The most recent PASSING challenge test (optionally for a recipe and
        within a time window) — used to gate production start."""
        with self._sf() as s:
            query = select(ChallengeTest).where(ChallengeTest.result == "pass")
            if recipe_id is not None:
                query = query.where(ChallengeTest.recipe_id == recipe_id)
            query = query.order_by(ChallengeTest.id.desc())
            for test in s.execute(query).scalars():
                if within_hours is not None and test.completed_at:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(test.completed_at)
                    if age.total_seconds() > within_hours * 3600:
                        return None
                return {"id": test.id, "completed_at": test.completed_at,
                        "trigger": test.trigger_reason}
            return None

    def list_tests(self, limit: int = 100, batch_id: int | None = None) -> list[dict]:
        with self._sf() as s:
            query = select(ChallengeTest).order_by(ChallengeTest.id.desc()).limit(limit)
            if batch_id is not None:
                query = query.where(ChallengeTest.batch_id == batch_id)
            out = []
            for t in s.execute(query).scalars():
                out.append({
                    "id": t.id, "trigger": t.trigger_reason, "result": t.result,
                    "gate": t.line_gate_action, "station": t.station,
                    "operator_id": t.operator_id, "completed_at": t.completed_at,
                    "shots": [{"label": sh.label, "expected": sh.expected_verdict,
                               "actual": sh.actual_verdict, "io": sh.reject_io_confirmed,
                               "passed": sh.passed} for sh in t.shots],
                })
            return out
