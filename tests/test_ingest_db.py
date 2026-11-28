"""Ingest and gold loading against a real, throwaway Postgres database.

Skipped automatically when Postgres isn't reachable: `make db-up` to run them.
"""

import uuid

import psycopg
import pytest
from psycopg import errors, sql

from triage.gold.load import gold_of, load_gold
from triage.ingest import db
from triage.ingest.load import ingest_scenario
from triage.ingest.migrate import apply_migrations, ensure_roles


@pytest.fixture(scope="module")
def dbname():
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
                apply_migrations(conn)
            yield name
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _one(dbname: str, role: db.Role, query: str, params: tuple = ()):
    with db.connect(role, dbname) as conn:
        return conn.execute(query, params).fetchone()[0]


def test_ingest_loads_lines_templates_and_rollups(dbname):
    rep = ingest_scenario("fx01", dbname=dbname)
    assert rep.unparsed_lines == 0
    assert rep.new_templates == rep.templates

    q = "SELECT count(*) FROM log_lines WHERE scenario_id = 'fx01'"
    assert _one(dbname, "rw", q) == rep.records
    q = "SELECT sum(n) FROM template_counts WHERE scenario_id = 'fx01'"
    assert _one(dbname, "rw", q) == rep.records
    q = "SELECT count(*) FROM log_lines WHERE scenario_id = 'fx01' AND raw LIKE %s"
    assert _one(dbname, "rw", q, ("%\n\tat %",)) > 0  # stack traces stay with their event
    spec = _one(dbname, "rw", "SELECT spec FROM scenarios WHERE scenario_id = 'fx01'")
    assert set(spec) == {"id", "system", "alert"}  # no fault/gold/distractors for triage_rw


def test_reingest_replaces_rows(dbname):
    first = ingest_scenario("fx01", dbname=dbname)
    second = ingest_scenario("fx01", dbname=dbname)
    assert second.new_templates == 0
    q = "SELECT count(*) FROM log_lines WHERE scenario_id = 'fx01'"
    assert _one(dbname, "rw", q) == first.records == second.records


def test_same_template_text_gets_the_same_id_across_scenarios(dbname):
    ingest_scenario("fx01", dbname=dbname)
    rep = ingest_scenario("fx02", dbname=dbname)
    assert rep.new_templates == 0  # fx02 only has background templates fx01 already stored
    q = (
        "SELECT count(DISTINCT template_id) FROM log_lines"
        " WHERE scenario_id = 'fx02' AND template_id IN"
        " (SELECT template_id FROM log_lines WHERE scenario_id = 'fx01')"
    )
    assert _one(dbname, "rw", q) == rep.templates


def test_gold_is_loaded_and_read_only_by_the_eval_role(dbname):
    ingest_scenario("fx01", dbname=dbname)
    scenario_id, gold = gold_of("fx01")
    with db.connect("eval", dbname) as conn:
        load_gold(conn, scenario_id, gold)
        load_gold(conn, scenario_id, gold)  # idempotent
    q = "SELECT gold FROM scenario_gold WHERE scenario_id = 'fx01'"
    assert _one(dbname, "eval", q) == gold
    with db.connect("rw", dbname) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM scenario_gold")


def test_gold_for_a_scenario_that_was_never_ingested_fails(dbname):
    with db.connect("eval", dbname) as conn, pytest.raises(errors.ForeignKeyViolation):
        load_gold(conn, "never-ingested", {"templates": []})


def test_query_tool_role_reads_ingested_logs(dbname):
    ingest_scenario("fx01", dbname=dbname)
    q = "SELECT count(*) FROM template_counts WHERE scenario_id = 'fx01'"
    assert _one(dbname, "ro", q) > 0
