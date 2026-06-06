from sqlalchemy import select

from vis.db.audit import AuditService
from vis.db.base import init_db, make_engine, make_session_factory
from vis.db.models import AuditEntry


def _sf(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(engine)
    return make_session_factory(engine)


def test_audit_chain_valid(tmp_path):
    sf = _sf(tmp_path)
    with sf() as s:
        audit = AuditService(s)
        audit.record("recipe.create", "recipe", 1, after={"version": 1})
        audit.record("recipe.approve", "recipe", 1, before={"status": "draft"}, after={"status": "approved"})
        s.commit()
    with sf() as s:
        ok, broken = AuditService(s).verify_chain()
        assert ok and broken is None


def test_audit_tamper_is_detected(tmp_path):
    sf = _sf(tmp_path)
    with sf() as s:
        audit = AuditService(s)
        audit.record("x", "entity", 1, after={"a": 1})
        audit.record("y", "entity", 1, after={"a": 2})
        s.commit()

    # Simulate someone editing a stored audit row directly in the DB.
    with sf() as s:
        first = s.execute(select(AuditEntry).order_by(AuditEntry.id.asc())).scalars().first()
        first.after = {"a": 999}
        s.commit()

    with sf() as s:
        ok, broken = AuditService(s).verify_chain()
        assert not ok
        assert broken is not None
