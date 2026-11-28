"""Shared data contracts between all pipeline stages.

DRAFT — copied from docs/01-master-architecture.md §6 and §8 for the Week-1 contract review.
This is a shared contract: once frozen, any change needs a PR labelled `contract-change`,
approval from all three members, and a bump of SCHEMA_VERSION.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

SCHEMA_VERSION = "0.1.0-draft"

# T:<template> · L:<line> · M:<metric> · R:<runbook>#<step> · P:<postmortem>#<section>
CitationId = Annotated[
    str,
    StringConstraints(pattern=r"^(T:[0-9a-f]{8}|L:\d+|M:[\w.-]+|R:[\w-]+#\d+|P:[\w-]+#[\w-]+)$"),
]


class FaultType(StrEnum):
    """Fault taxonomy (architecture §8). Member 2 leads the final wording."""

    CPU_SATURATION = "cpu_saturation"
    MEMORY_EXHAUSTION = "memory_exhaustion"
    DISK_PRESSURE = "disk_pressure"
    NETWORK_DELAY = "network_delay"
    NETWORK_LOSS = "network_loss"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    DB_POOL_EXHAUSTION = "db_connection_pool_exhaustion"
    SLOW_QUERY_LOCK = "slow_query_lock_contention"
    BAD_CONFIG_DEPLOY = "bad_config_deploy"
    AUTH_CERT_FAILURE = "auth_cert_failure"
    CODE_EXCEPTION = "code_exception"
    UNKNOWN = "unknown"


# ---------- input ----------
class Alert(BaseModel):
    alert_id: str
    scenario_id: str
    service: str
    ts: datetime
    symptom: str
    severity: Literal["low", "high", "critical"] = "high"


# ---------- M2 output: evidence pack ----------
class PackLine(BaseModel):
    cite: CitationId  # "L:…"
    ts: datetime
    text: str  # raw line, secrets redacted, truncated to 300 chars


class PackTemplate(BaseModel):
    cite: CitationId  # "T:…"
    service: str
    level: str
    template: str
    count_alert: int
    count_baseline: float  # rescaled to alert-window length
    rate_ratio: float
    novel: bool
    onset: datetime | None
    score: float
    examples: list[PackLine]


class MetricAnomaly(BaseModel):
    cite: CitationId  # "M:…"
    service: str
    name: str
    zscore: float
    onset: datetime | None


class EvidencePack(BaseModel):
    pack_id: str
    alert: Alert
    window: tuple[datetime, datetime]
    baseline: tuple[datetime, datetime]
    services: list[str]
    templates: list[PackTemplate]
    metrics: list[MetricAnomaly] = []
    token_count: int
    config_hash: str


# ---------- M3 output: NLP signals ----------
class Entity(BaseModel):
    text: str
    label: Literal["SERVICE", "HOST", "ENDPOINT", "ERROR_CODE", "EXCEPTION", "RESOURCE"]
    source: CitationId


class FaultPrediction(BaseModel):
    probs: dict[FaultType, float]
    top: FaultType
    model: str


class NlpSignals(BaseModel):
    entities: list[Entity]
    fault: FaultPrediction


class RetrievalQuery(BaseModel):
    text: str
    fault_type: FaultType | None
    entities: list[str]


# ---------- M4 output: retrieved knowledge ----------
class KBChunk(BaseModel):
    cite: CitationId  # "R:…" or "P:…"
    doc_type: Literal["runbook", "postmortem"]
    title: str
    text: str
    score: float


# ---------- M5 output: candidate causes ----------
class Claim(BaseModel):
    kind: Literal["observation", "inference", "remediation"]
    text: str
    cites: list[CitationId] = Field(min_length=1)


class CandidateCause(BaseModel):
    service: str
    fault_type: FaultType
    explanation: str
    claims: list[Claim] = Field(min_length=1)
    fix_steps: list[Claim] = []  # kind == "remediation"


class CandidateCauses(BaseModel):
    causes: list[CandidateCause] = Field(max_length=3)
    insufficient_evidence_reason: str | None = None


# ---------- M5 → M6: what the LLM was shown ----------
class LedgerEntry(BaseModel):
    cite: CitationId
    origin: Literal["pack", "tool", "retrieval"]
    shown: dict  # exactly what the LLM saw: service, counts, onset, text …


class Ledger(BaseModel):
    entries: dict[CitationId, LedgerEntry]


# ---------- M6 output: verification ----------
class ClaimVerdict(BaseModel):
    claim: Claim
    exists: bool
    supported: bool
    method: Literal["exact", "count_check", "entity_check", "nli", "none"]
    nli_entailment: float | None = None
    reason: str = ""


class VerifiedCause(BaseModel):
    rank: int
    cause: CandidateCause
    verdicts: list[ClaimVerdict]
    confidence: float
    fix_verified: bool


class VerificationResult(BaseModel):
    status: Literal["answered", "abstained"]
    causes: list[VerifiedCause]  # survivors, ranked
    dropped: list[VerifiedCause] = []  # failed verification; kept for UI and verifier eval
    abstain_reason: str | None = None


# ---------- final output ----------
class Cost(BaseModel):
    tokens_in: int
    tokens_out: int
    tool_calls: int
    latency_ms: int


class TriageResult(BaseModel):
    run_id: str
    alert: Alert
    status: Literal["answered", "abstained"]
    causes: list[VerifiedCause]
    dropped: list[VerifiedCause] = []
    summary: str
    abstain_reason: str | None = None
    pack_id: str
    retrieved: list[CitationId]
    cost: Cost
    config_hash: str
