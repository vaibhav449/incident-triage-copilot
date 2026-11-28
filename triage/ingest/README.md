# triage/ingest — M1 log parsing and ingestion (owner: Member 1)

`triage ingest <scenario>` reads `logs/<service>.log` from a scenario folder and loads it into Postgres as `triage_rw`. A line goes through the steps of architecture §5 M1:

1. **Format adapter** (`formats.py`): one parser per format. FaultLab's map is gateway → nginx, auth/notification → Python logging, catalog/payment → logback, cart → key=value. A line with no header (a stack-trace line, say) is joined to the previous record's `raw`.
2. **Redaction** (`masking.redact`): passwords, tokens, keys and Luhn-valid card numbers are removed from `raw`. Everything else stays, so `L:` citations are readable.
3. **Drain3** (`templates.py`): a fresh miner per scenario, with typed masks. Masks become `<*>` in the stored template, and `template_id = sha1(final template)[:8]` is assigned once the whole scenario has been mined.
4. **Load** (`load.py`): one transaction upserts `scenarios`, inserts new `templates` (and fails if two different texts get the same ID), `COPY`s into `log_lines` in time order, and builds the per-minute `template_counts`. Running it again replaces the scenario's rows.

`scenarios.spec` holds an **allowlist** from `scenario.yaml`: id, system, and the alert's service, symptom, severity and time. `fault:`, `distractors:` and `timeline:` would give the answer away, so they are left out along with `gold:` (see `scenario.py`). Gold labels are loaded separately by `triage gold load` (in `triage/gold/`, connecting as `triage_eval`).

**Why this change (fixture PR):** handoff H2 needs ingested scenarios with gold in Week 1. FaultLab doesn't exist yet, so `tests/fixtures/` has two synthetic scenarios that go through this real ingest path. `--dry-run` parses without a database.

**Not done yet:** `*.log.zst` input, persisted Drain3 state for RCAEval-scale systems, Drain3 `depth` / `sim_th` tuning on Loghub-2.0 (the defaults merge different gateway endpoints that return 200), and the LLM-parser comparison.
