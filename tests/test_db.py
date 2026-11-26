"""Schema and role-privilege tests against a real Postgres.

Each run creates a throwaway database, so the dev database is never touched.
Skipped automatically when Postgres isn't reachable (e.g. in CI for now): `make db-up`.
"""

import uuid

import psycopg
import pytest
from psycopg import errors, sql
from psycopg.types.json import Jsonb

from triage.ingest import db
from triage.ingest.migrate import apply_migrations, ensure_roles, status


@pytest.fixture(scope="module")
def test_db():
    try:
        admin = psycopg.connect(db.admin_dsn(), autocommit=True, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running — `make db-up` to run DB tests")
    name = f"triage_test_{uuid.uuid4().hex[:12]}"
    with admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(db.admin_dsn(name), autocommit=True) as conn:
                ensure_roles(conn)
                first = apply_migrations(conn)
                second = apply_migrations(conn)
                # Seed one scenario + template + log line for the role tests.
                conn.execute("INSERT INTO scenarios VALUES ('seed', 'faultlab', 'dev', '{}')")
                conn.execute(
                    "INSERT INTO templates VALUES ('5eed0001', 'Timeout <*>', 'drain3', 1)"
                )
                conn.execute(
                    "INSERT INTO log_lines (scenario_id, ts, service, template_id, raw,"
                    " source_file, line_no) VALUES"
                    " ('seed', now(), 'svc', '5eed0001', 'Timeout 5', 'a.log', 1)"
                )
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                ]
                versions = status(conn)
            yield {
                "name": name,
                "first": first,
                "second": second,
                "status": versions,
                "tables": tables,
            }
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _conn(role: db.Role, test_db) -> psycopg.Connection:
    return db.connect(role, test_db["name"], autocommit=True)


def test_migrations_apply_once_and_report_status(test_db):
    assert test_db["first"] == ["001_tables", "002_grants"]
    assert test_db["second"] == []
    assert test_db["status"] == [("001_tables", True), ("002_grants", True)]


def test_rw_writes_pipeline_tables_but_cannot_read_gold(test_db):
    with _conn("rw", test_db) as conn:
        conn.execute("INSERT INTO scenarios VALUES ('rw-check', 'faultlab', NULL, '{}')")
        line_id = conn.execute(
            "INSERT INTO log_lines (scenario_id, ts, service, raw, source_file, line_no)"
            " VALUES ('rw-check', now(), 'svc', 'hello', 'b.log', 1) RETURNING line_id"
        ).fetchone()[0]
        assert line_id > 0
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM scenario_gold")


def test_ro_reads_log_tables_only_and_cannot_write(test_db):
    with _conn("ro", test_db) as conn:
        assert conn.execute("SELECT count(*) FROM log_lines").fetchone()[0] >= 1
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "2s"
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM scenarios")
        # Even with read-only mode switched off, the grants alone forbid writing.
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("INSERT INTO templates VALUES ('ffffffff', 'x', 'drain3', 0)")


def test_eval_reads_and_writes_gold_but_not_logs(test_db):
    with _conn("eval", test_db) as conn:
        conn.execute(
            "INSERT INTO scenario_gold VALUES ('seed', %s)", (Jsonb({"root_service": "svc"}),)
        )
        gold = conn.execute("SELECT gold FROM scenario_gold WHERE scenario_id = 'seed'").fetchone()
        assert gold[0] == {"root_service": "svc"}
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute("DELETE FROM log_lines")


def test_every_table_has_the_right_rw_grant(test_db):
    """Guard for future migrations: a new table without grants fails here."""
    hidden_from_rw = {"scenario_gold", "schema_migrations"}
    with _conn("rw", test_db) as conn:
        for table in test_db["tables"]:
            can_read = conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT')", (table,)
            ).fetchone()[0]
            assert can_read == (table not in hidden_from_rw), table
