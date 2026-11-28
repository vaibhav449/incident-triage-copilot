"""The two fixture scenarios (handoff H2): reproducible, correct gold, and no answer leakage.

Tests may read the gold block; pipeline code may not (CLAUDE.md invariant 3).
"""

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from triage.cli import discover
from triage.ingest.load import parse_scenario
from triage.ingest.scenario import pipeline_spec, read_yaml, resolve

FIXTURES = Path(__file__).parent / "fixtures"


def _builder():
    spec = importlib.util.spec_from_file_location("build_fixtures", FIXTURES / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def test_committed_fixtures_match_a_fresh_build(tmp_path):
    _builder().build(tmp_path)
    committed = FIXTURES / "scenarios"
    assert _files(committed) == _files(tmp_path)
    for rel in _files(committed):
        assert (committed / rel).read_bytes() == (tmp_path / rel).read_bytes(), (
            f"{rel} is stale: run `uv run python tests/fixtures/build_fixtures.py` and commit"
        )


@pytest.mark.parametrize("sid", ["fx01", "fx02"])
def test_fixture_parses_completely(sid):
    parsed = parse_scenario(sid)
    logs = parsed.logs
    assert logs.files == 6
    assert logs.unparsed_lines == 0
    assert {r.service for r in logs.records} == {
        "gateway",
        "auth-svc",
        "catalog-svc",
        "cart-svc",
        "payment-svc",
        "notification-svc",
    }
    assert all(r.template_id in logs.templates for r in logs.records)
    assert [r.ts for r in logs.records] == sorted(r.ts for r in logs.records)


def test_fx01_gold_templates_are_near_the_root_novel_and_in_the_alert_window():
    doc = read_yaml(resolve("fx01"))
    gold = doc["gold"]
    assert gold["root_cause"] == {
        "service": "payment-svc",
        "fault_type": "db_connection_pool_exhaustion",
    }
    assert gold["should_abstain"] is False
    assert len(gold["templates"]) >= 3

    records = parse_scenario("fx01").logs.records
    alert = datetime.fromisoformat(doc["run"]["alert_ts"])
    window = (alert - timedelta(minutes=15), alert + timedelta(minutes=2))  # architecture §5 M2
    baseline = (alert - timedelta(minutes=75), window[0])
    for tid in gold["templates"]:
        hits = [r for r in records if r.template_id == tid]
        assert {r.service for r in hits} <= {"payment-svc", "cart-svc", "notification-svc"}
        assert any(window[0] <= r.ts <= window[1] for r in hits), tid
        assert not any(baseline[0] <= r.ts < baseline[1] for r in hits), tid


def test_fx01_keeps_stack_traces_with_their_event():
    records = parse_scenario("fx01").logs.records
    traced = [r for r in records if "\n\tat " in r.raw]
    assert traced
    assert all(r.service == "payment-svc" and "\n" not in r.message for r in traced)


def test_fx02_is_a_no_fault_scenario():
    gold = read_yaml(resolve("fx02"))["gold"]
    assert gold["should_abstain"] is True
    assert gold["templates"] == []
    assert gold["root_cause"] == {"service": None, "fault_type": "unknown"}


@pytest.mark.parametrize("sid", ["fx01", "fx02"])
def test_pipeline_spec_reveals_nothing_about_the_answer(sid):
    doc = read_yaml(resolve(sid))
    spec = pipeline_spec(doc)
    assert set(spec) == {"id", "system", "alert"}
    assert set(spec["alert"]) == {"service", "symptom", "severity", "ts"}
    values = str(spec)
    if doc["fault"]:
        assert doc["fault"]["root_service"] not in values
        assert doc["fault"]["type"] not in values
    for distractor in doc["distractors"]:
        assert distractor["service"] not in values


def test_cli_dry_run():
    root = typer.Typer()
    root.callback()(lambda: None)
    discover(root=root)
    result = CliRunner().invoke(root, ["ingest", "fx01", "fx02", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "fx01: 6 files" in result.output
    assert "0 unparsed" in result.output
