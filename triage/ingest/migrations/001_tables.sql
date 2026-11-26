-- 001_tables: core schema (docs/01-master-architecture.md §7.1).
-- Gold labels live ONLY in scenario_gold; scenarios.spec never holds the gold block.

CREATE TABLE scenarios (
    scenario_id   text PRIMARY KEY,
    system        text NOT NULL,                -- faultlab | rcaeval-re2-ob | ...
    split         text CHECK (split IN ('train', 'dev', 'test')),  -- set by `triage split assign`
    spec          jsonb NOT NULL                -- scenario.yaml WITHOUT the gold block
);

CREATE TABLE scenario_gold (                    -- readable only by triage_eval (see 002_grants)
    scenario_id   text PRIMARY KEY REFERENCES scenarios ON DELETE CASCADE,
    gold          jsonb NOT NULL
);

CREATE TABLE templates (
    template_id   char(8) PRIMARY KEY,          -- sha1(final template text)[:8]
    template      text NOT NULL,
    parser        text NOT NULL,                -- drain3 | llm
    n_params      int  NOT NULL
);

CREATE TABLE log_lines (
    line_id       bigserial PRIMARY KEY,        -- citation ID L:<line_id>
    scenario_id   text NOT NULL REFERENCES scenarios ON DELETE CASCADE,
    ts            timestamptz NOT NULL,
    service       text NOT NULL,
    host          text,
    level         text,
    template_id   char(8) REFERENCES templates,
    params        jsonb,
    raw           text NOT NULL,                -- secrets/PII redacted
    source_file   text NOT NULL,
    line_no       int  NOT NULL
);
CREATE INDEX log_lines_scenario_service_ts ON log_lines (scenario_id, service, ts);
CREATE INDEX log_lines_scenario_template_ts ON log_lines (scenario_id, template_id, ts);

CREATE TABLE template_counts (                  -- 1-minute rollups for fast scoring
    scenario_id   text NOT NULL REFERENCES scenarios ON DELETE CASCADE,
    service       text NOT NULL,
    template_id   char(8) NOT NULL REFERENCES templates,
    level         text,
    bucket        timestamptz NOT NULL,
    n             int NOT NULL,
    PRIMARY KEY (scenario_id, service, template_id, bucket)
);

CREATE TABLE metrics (
    scenario_id   text NOT NULL REFERENCES scenarios ON DELETE CASCADE,
    service       text NOT NULL,
    name          text NOT NULL,
    ts            timestamptz NOT NULL,
    value         double precision NOT NULL
);
CREATE INDEX metrics_scenario_service_name_ts ON metrics (scenario_id, service, name, ts);

CREATE TABLE kb_chunks (                        -- data owned by Member 2 (M4)
    chunk_id      text PRIMARY KEY,             -- "R:rb-db-pool-exhaustion#4" / "P:…#…"
    doc_id        text NOT NULL,
    doc_type      text NOT NULL CHECK (doc_type IN ('runbook', 'postmortem')),
    title         text,
    section       text,
    step_no       int,
    text          text NOT NULL,
    meta          jsonb
);

CREATE TABLE evidence_packs (
    pack_id       text PRIMARY KEY,
    scenario_id   text REFERENCES scenarios ON DELETE CASCADE,
    config_hash   text,
    body          jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE triage_runs (
    run_id        text PRIMARY KEY,
    scenario_id   text REFERENCES scenarios ON DELETE CASCADE,
    config_hash   text,
    git_sha       text,
    result        jsonb NOT NULL,
    tokens_in     int,
    tokens_out    int,
    latency_ms    int,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE feedback (
    id            bigserial PRIMARY KEY,
    run_id        text REFERENCES triage_runs ON DELETE CASCADE,
    cause_rank    int,
    decision      text NOT NULL CHECK (decision IN ('approve', 'reject')),
    note          text,
    at            timestamptz NOT NULL DEFAULT now()
);
