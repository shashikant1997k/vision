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
    _auto_add_missing_columns(engine)


def _auto_add_missing_columns(engine) -> None:
    """Dev convenience: ADD COLUMN for any new model columns missing from an
    existing table, so a schema change doesn't break a dev database. Production
    uses Alembic migrations."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            coltype = column.type.compile(engine.dialect)
            default_sql = ""
            arg = getattr(column.default, "arg", None) if column.default is not None else None
            if arg is not None and not callable(arg):
                default_sql = f" DEFAULT {arg!r}" if isinstance(arg, str) else f" DEFAULT {arg}"
            with engine.begin() as conn:
                conn.execute(
                    text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {coltype}{default_sql}")
                )
