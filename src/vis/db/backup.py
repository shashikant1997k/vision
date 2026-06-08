"""Database backup / restore.

For the default SQLite deployment this uses SQLite's online backup API (a
consistent snapshot even while the app is running). Postgres deployments back up
with pg_dump (out of scope here). Backups support disaster recovery and station
cloning; the audit trail and e-signatures travel with the DB.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def _sqlite_path(engine) -> str | None:
    if engine.url.get_backend_name().startswith("sqlite") and engine.url.database:
        return engine.url.database
    return None


def backup_database(engine, dest: str) -> str:
    """Write a consistent backup of the database to `dest`. Returns the path."""
    src = _sqlite_path(engine)
    if src is None:
        raise RuntimeError("backup_database currently supports SQLite (use pg_dump for Postgres)")
    import sqlite3

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return dest


def restore_database(engine, src: str) -> str:
    """Restore the database from a backup file (overwrites the live DB)."""
    dest = _sqlite_path(engine)
    if dest is None:
        raise RuntimeError("restore_database currently supports SQLite")
    engine.dispose()
    shutil.copyfile(src, dest)
    return dest


def main() -> int:
    import argparse
    import os

    from .base import make_engine

    parser = argparse.ArgumentParser(description="Backup or restore the vision database")
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("file", help="backup file path")
    parser.add_argument("--db", help="DATABASE_URL (default: app data dir)")
    args = parser.parse_args()

    url = args.db or os.environ.get("DATABASE_URL") or f"sqlite:///{Path.home() / '.vision-inspection' / 'vis.db'}"
    engine = make_engine(url)
    if args.action == "backup":
        print("Backed up to", backup_database(engine, args.file))
    else:
        print("Restored from", restore_database(engine, args.file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
