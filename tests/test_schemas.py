"""Contract tests for triage/schemas.py, using the worked example from architecture §4."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from triage.schemas import (
    SCHEMA_VERSION,
    Alert,
    CandidateCause,
    CandidateCauses,
    Claim,
    Cost,
    FaultType,
    Ledger,
    LedgerEntry,
    TriageResult,
    VerificationResult,
    VerifiedCause,
)

TS = datetime(2026, 3, 14, 10, 42, tzinfo=UTC)


def _cause() -> CandidateCause:
    return CandidateCause(
        service="payment-svc",
        fault_type=FaultType.DB_POOL_EXHAUSTION,
        explanation="payment-svc exhausted its DB pool; gateway 504s are downstream.",
        claims=[
            Claim(
                kind="observation",
                text="payment-svc timed out on pool acquisition 412 times from 10:31.",
                cites=["T:a3f9c2e1", "L:1849302"],
            )
        ],
        fix_steps=[
            Claim(
                kind="remediation",
                text="Terminate long-held transactions on the payment DB.",
                cites=["R:rb-db-pool-exhaustion#4"],
            )
        ],
    )


def test_schema_version_is_set():
    assert SCHEMA_VERSION


def test_worked_example_round_trips_through_json():
    alert = Alert(alert_id="a1", scenario_id="s017", service="gateway", ts=TS, symptom="p99 > 2s")
    verified = VerifiedCause(rank=1, cause=_cause(), verdicts=[], confidence=0.8, fix_verified=True)
    verification = VerificationResult(status="answered", causes=[verified])
    result = TriageResult(
        run_id="r1",
        alert=alert,
        status=verification.status,
        causes=verification.causes,
        summary="payment-svc DB pool exhaustion",
        pack_id="p1",
        retrieved=["R:rb-db-pool-exhaustion#4"],
        cost=Cost(tokens_in=1200, tokens_out=300, tool_calls=1, latency_ms=9000),
        config_hash="abc",
    )
    assert TriageResult.model_validate_json(result.model_dump_json()) == result


def test_claim_without_citation_is_rejected():
    with pytest.raises(ValidationError):
        Claim(kind="observation", text="no evidence", cites=[])


@pytest.mark.parametrize("bad", ["T:XYZ", "L:abc", "R:runbook-without-step", "payment-svc", ""])
def test_malformed_citation_ids_are_rejected(bad):
    with pytest.raises(ValidationError):
        Claim(kind="observation", text="x", cites=[bad])


@pytest.mark.parametrize(
    "good",
    [
        "T:a3f9c2e1",
        "L:1849302",
        "M:payment-svc.db_pool_in_use",
        "R:rb-db-pool#4",
        "P:pm-1#timeline",
    ],
)
def test_valid_citation_ids_are_accepted(good):
    assert Claim(kind="observation", text="x", cites=[good]).cites == [good]


def test_at_most_three_causes():
    with pytest.raises(ValidationError):
        CandidateCauses(causes=[_cause()] * 4)


def test_ledger_keys_are_citation_ids():
    entry = LedgerEntry(cite="T:a3f9c2e1", origin="pack", shown={"count_alert": 412})
    assert Ledger(entries={"T:a3f9c2e1": entry}).entries["T:a3f9c2e1"].shown["count_alert"] == 412
    with pytest.raises(ValidationError):
        Ledger(entries={"not-an-id": entry})
