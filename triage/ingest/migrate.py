"""Create the application roles and apply SQL migrations (architecture §7.1).

All functions expect an **autocommit** superuser connection (`db.admin_dsn()`); each
migration file runs inside its own transaction together with its bookkeeping row.
"""

from pathlib import Path

import psycopg
from psycopg import sql

from triage.ingest.db import ROLE_NAMES, role_password

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_LOCK_ID = 7_312_026  # arbitrary key for pg_advisory_xact_lock: one migrator at a time


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def ensure_roles(conn: psycopg.Connection) -> None:
    """Create the three login roles, or update their passwords. Idempotent."""
    with conn.transaction():
        for role, name in ROLE_NAMES.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
            verb = sql.SQL("ALTER ROLE" if exists else "CREATE ROLE")
            conn.execute(
                sql.SQL("{} {} LOGIN PASSWORD {}").format(
                    verb, sql.Identifier(name), sql.Literal(role_password(role))
                )
            )
        ro = sql.Identifier(ROLE_NAMES["ro"])
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '2s'").format(ro))
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(ro))


def _ensure_bookkeeping(conn: psycopg.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY,"
        " applied_at timestamptz NOT NULL DEFAULT now())"
    )


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every pending migration in order; return the versions applied."""
    applied = []
    for path in migration_files():
        version = path.stem
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
            _ensure_bookkeeping(conn)
            done = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
            ).fetchone()
            if done:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied.append(version)
    return applied


def status(conn: psycopg.Connection) -> list[tuple[str, bool]]:
    """(version, applied?) for every migration file. Read-only."""
    applied: set[str] = set()
    if conn.execute("SELECT to_regclass('schema_migrations')").fetchone()[0] is not None:
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    return [(path.stem, path.stem in applied) for path in migration_files()]
