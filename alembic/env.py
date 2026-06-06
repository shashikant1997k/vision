"""Alembic environment — wires migrations to our SQLAlchemy metadata.

DB URL comes from DATABASE_URL (see vis.db.base.get_database_url).
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from vis.db.base import Base, get_database_url
import vis.db.models  # noqa: F401  register all tables on Base.metadata

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
