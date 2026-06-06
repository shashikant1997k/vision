"""Persistence layer — PostgreSQL + JSONB via SQLAlchemy (D-013).

Runs on SQLite for dev/tests (no driver needed); set DATABASE_URL to a
PostgreSQL DSN for production. Includes a hash-chained, append-only audit
trail (Part 11 / 21 CFR 11.10(e)).
"""
