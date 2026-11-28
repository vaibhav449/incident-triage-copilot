"""Copy a scenario's `gold:` block from scenario.yaml into `scenario_gold` (as `triage_eval`)."""

from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from triage.ingest.scenario import read_yaml, resolve


def gold_of(ref: str | Path) -> tuple[str, dict[str, Any]]:
    """(scenario_id, gold block) for a scenario id or folder."""
    doc = read_yaml(resolve(ref))
    gold = doc.get("gold")
    if not isinstance(gold, dict):
        raise ValueError(f"scenario {doc['id']!r} has no `gold:` block")
    return doc["id"], gold


def load_gold(conn: psycopg.Connection, scenario_id: str, gold: dict[str, Any]) -> None:
    """Upsert one gold row. The scenario must already be ingested (foreign key)."""
    conn.execute(
        "INSERT INTO scenario_gold (scenario_id, gold) VALUES (%s, %s)"
        " ON CONFLICT (scenario_id) DO UPDATE SET gold = EXCLUDED.gold",
        (scenario_id, Jsonb(gold)),
    )
