"""`ingest_scenario`: parse a scenario's logs and bulk-load them (architecture §5 M1).

Steps: format adapter → secret redaction → Drain3 → `COPY` into `log_lines` → per-minute
rollups in `template_counts`. Parsing (`parse_scenario`) needs no database, so the fixture
builder and the tests use it on its own. Re-ingesting a scenario replaces its rows, so it
is safe to repeat (its `line_id`s change).
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from triage.ingest import db
from triage.ingest.formats import ADAPTERS, format_for
from triage.ingest.masking import redact
from triage.ingest.models import IngestConfig, IngestReport, LogRecord
from triage.ingest.scenario import log_files, pipeline_spec, read_yaml, resolve, split_of
from triage.ingest.templates import TemplateCollisionError, mine


@dataclass
class ParsedLogs:
    records: list[LogRecord]  # sorted by (ts, source_file, line_no), template IDs set
    templates: dict[str, str]  # template_id -> template
    files: int
    source_lines: int
    continuation_lines: int
    unparsed_lines: int


@dataclass
class ParsedScenario:
    scenario_id: str
    system: str
    split: str | None
    spec: dict[str, Any]
    logs: ParsedLogs


def read_log_file(
    path: Path, service: str, fmt: str, source_file: str
) -> tuple[list[LogRecord], int, int, int]:
    """Parse one file → (records, source lines, continuation lines, unparsed lines)."""
    adapter = ADAPTERS[fmt]
    records: list[LogRecord] = []
    source = continuation = unparsed = 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            source += 1
            raw = redact(line.rstrip("\r\n"))
            if not raw.strip():
                continue
            parsed = adapter(raw, service)
            if parsed is not None:
                records.append(
                    LogRecord(
                        parsed.ts,
                        parsed.service,
                        parsed.host,
                        parsed.level,
                        parsed.message,
                        raw,
                        source_file,
                        line_no,
                    )
                )
            elif records:  # stack trace or wrapped message: belongs to the previous event
                records[-1].raw += "\n" + raw
                continuation += 1
            else:
                unparsed += 1
    return records, source, continuation, unparsed


def parse_logs(scenario_dir: Path, system: str, cfg: IngestConfig) -> ParsedLogs:
    records: list[LogRecord] = []
    files = source = continuation = unparsed = 0
    for path in log_files(scenario_dir):
        service = path.name.removesuffix(".log")
        rel = path.relative_to(scenario_dir).as_posix()
        recs, s, c, u = read_log_file(path, service, format_for(system, service), rel)
        records += recs
        files += 1
        source, continuation, unparsed = source + s, continuation + c, unparsed + u
    records.sort(key=lambda r: (r.ts, r.source_file, r.line_no))
    templates = mine(records, cfg)
    return ParsedLogs(records, templates, files, source, continuation, unparsed)


def parse_scenario(ref: str | Path, cfg: IngestConfig | None = None) -> ParsedScenario:
    scenario_dir = resolve(ref)
    doc = read_yaml(scenario_dir)
    logs = parse_logs(scenario_dir, doc["system"], cfg or IngestConfig())
    return ParsedScenario(doc["id"], doc["system"], split_of(doc), pipeline_spec(doc), logs)


_SEVERITY = (
    "CASE level WHEN 'FATAL' THEN 5 WHEN 'ERROR' THEN 4 WHEN 'WARN' THEN 3"
    " WHEN 'INFO' THEN 2 WHEN 'DEBUG' THEN 1 ELSE 0 END"
)
_ROLLUP = f"""
INSERT INTO template_counts (scenario_id, service, template_id, level, bucket, n)
SELECT scenario_id, service, template_id,
       (array_agg(level ORDER BY {_SEVERITY} DESC))[1],
       date_trunc('minute', ts), count(*)
FROM log_lines
WHERE scenario_id = %s AND template_id IS NOT NULL
GROUP BY scenario_id, service, template_id, date_trunc('minute', ts)
"""
_COPY = (
    "COPY log_lines (scenario_id, ts, service, host, level, template_id, params, raw,"
    " source_file, line_no) FROM STDIN"
)


def _upsert_templates(conn: psycopg.Connection, templates: dict[str, str]) -> int:
    """Insert templates the shared table doesn't have yet; return how many were new."""
    existing = dict(
        conn.execute(
            "SELECT template_id, template FROM templates WHERE template_id = ANY(%s)",
            (list(templates),),
        ).fetchall()
    )
    clashes = [t for t in templates if t in existing and existing[t] != templates[t]]
    if clashes:
        tid = clashes[0]
        raise TemplateCollisionError(f"{tid}: stored {existing[tid]!r} vs new {templates[tid]!r}")
    new = [
        (t, text, "drain3", text.count("<*>")) for t, text in templates.items() if t not in existing
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO templates (template_id, template, parser, n_params)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT (template_id) DO NOTHING",
            new,
        )
    return len(new)


def write_scenario(conn: psycopg.Connection, parsed: ParsedScenario) -> int:
    """Replace the scenario's rows in one transaction. Returns the number of new templates."""
    sid = parsed.scenario_id
    with conn.transaction():
        conn.execute(
            "INSERT INTO scenarios (scenario_id, system, split, spec) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (scenario_id) DO UPDATE SET system = EXCLUDED.system,"
            " spec = EXCLUDED.spec, split = COALESCE(EXCLUDED.split, scenarios.split)",
            (sid, parsed.system, parsed.split, Jsonb(parsed.spec)),
        )
        conn.execute("DELETE FROM template_counts WHERE scenario_id = %s", (sid,))
        conn.execute("DELETE FROM log_lines WHERE scenario_id = %s", (sid,))
        new_templates = _upsert_templates(conn, parsed.logs.templates)
        with conn.cursor() as cur, cur.copy(_COPY) as copy:
            for r in parsed.logs.records:
                params = None if r.params is None else json.dumps(r.params)
                copy.write_row(
                    [
                        sid,
                        r.ts,
                        r.service,
                        r.host,
                        r.level,
                        r.template_id,
                        params,
                        r.raw,
                        r.source_file,
                        r.line_no,
                    ]
                )
        conn.execute(_ROLLUP, (sid,))
    return new_templates


def ingest_scenario(
    ref: str | Path, cfg: IngestConfig | None = None, *, dbname: str | None = None
) -> IngestReport:
    """Parse and load one scenario as `triage_rw` (architecture §6.3 entry point)."""
    started = time.perf_counter()
    parsed = parse_scenario(ref, cfg)
    with db.connect("rw", dbname, connect_timeout=5) as conn:
        new_templates = write_scenario(conn, parsed)
    return report(parsed, new_templates, time.perf_counter() - started)


def report(parsed: ParsedScenario, new_templates: int, seconds: float) -> IngestReport:
    logs = parsed.logs
    return IngestReport(
        scenario_id=parsed.scenario_id,
        files=logs.files,
        source_lines=logs.source_lines,
        records=len(logs.records),
        continuation_lines=logs.continuation_lines,
        unparsed_lines=logs.unparsed_lines,
        templates=len(logs.templates),
        new_templates=new_templates,
        first_ts=logs.records[0].ts if logs.records else None,
        last_ts=logs.records[-1].ts if logs.records else None,
        seconds=round(seconds, 3),
    )
