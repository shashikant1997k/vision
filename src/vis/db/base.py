from __future__ import annotations

import os

from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


# JSONB on PostgreSQL (indexable, typed), plain JSON elsewhere (e.g. SQLite).
JSONType = JSON().with_variant(JSONB, "postgresql")


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///vis.db")


def make_engine(url: str | None = None):
    u = url or get_database_url()
    kwargs: dict = {"future": True}
    if u.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(u, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def init_db(engine) -> None:
    """Create all tables. Dev/test convenience — production uses Alembic
    migrations (D-013)."""
    from . import models  # noqa: F401  ensure models are registered on Base

    Base.metadata.create_all(engine)
