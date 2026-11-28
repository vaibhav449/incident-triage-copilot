"""Records, config and report for M1 ingestion.

These types are internal to `triage/ingest/`. They are not part of the shared contract in
`triage/schemas.py`; nothing downstream reads them (later stages read Postgres).
"""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IngestConfig(BaseModel):
    """Parser settings (architecture §5 M1). Drain3 defaults until tuned on Loghub-2.0."""

    model_config = ConfigDict(frozen=True)

    drain_depth: int = 4
    drain_sim_th: float = 0.4
    drain_max_children: int = 100
    extract_params: bool = True


@dataclass(slots=True)
class ParsedLine:
    """Header fields a format adapter extracts from one raw line."""

    ts: datetime  # always timezone-aware (UTC when the format has no offset)
    service: str
    host: str | None
    level: str | None  # DEBUG | INFO | WARN | ERROR | FATAL
    message: str  # the part Drain3 mines; header fields removed


@dataclass(slots=True)
class LogRecord:
    """One row of `log_lines`, before it gets a `line_id`."""

    ts: datetime
    service: str
    host: str | None
    level: str | None
    message: str
    raw: str  # full event text, secrets redacted; continuation lines joined with "\n"
    source_file: str  # relative to the scenario folder, e.g. "logs/payment-svc.log"
    line_no: int  # 1-based line of the event's first line in source_file
    template_id: str | None = None
    params: list[str] | None = None


class IngestReport(BaseModel):
    """What `ingest_scenario` did. Printed by `triage ingest`."""

    scenario_id: str
    files: int
    source_lines: int  # physical lines read, blank lines included
    records: int  # rows written to log_lines
    continuation_lines: int  # e.g. stack-trace lines folded into the previous record
    unparsed_lines: int  # lines with no header and no previous record to attach to
    templates: int
    new_templates: int = 0  # templates not yet in the shared `templates` table
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    seconds: float = 0.0
