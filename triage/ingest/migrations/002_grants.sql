-- 002_grants: who may touch what (docs/01-master-architecture.md §7.1).
-- Roles themselves are created by `triage db migrate` (migrate.ensure_roles) before this runs.
--
-- RULE FOR FUTURE MIGRATIONS: every new table must grant its own privileges in the same
-- migration. We deliberately do NOT use ALTER DEFAULT PRIVILEGES, so a new gold-like table
-- can never be exposed to triage_rw by accident. tests/test_db.py fails if triage_rw
-- cannot read a table it should.

-- Nobody but the eval role ever sees ground truth.
REVOKE ALL ON scenario_gold FROM PUBLIC;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO triage_rw, triage_ro, triage_eval',
                   current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO triage_rw, triage_ro, triage_eval;

-- triage_rw: ingest, pipeline and API. Everything except gold.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    scenarios, templates, log_lines, template_counts, metrics,
    kb_chunks, evidence_packs, triage_runs, feedback
TO triage_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO triage_rw;

-- triage_ro: the LLM's read-only query tools. Log tables only.
-- (statement_timeout and default_transaction_read_only are set on the role in ensure_roles.)
GRANT SELECT ON log_lines, templates, template_counts TO triage_ro;

-- triage_eval: evaluation harness and `triage gold label`. Reads everything, writes gold + runs.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO triage_eval;
GRANT INSERT, UPDATE, DELETE ON scenario_gold, triage_runs TO triage_eval;
