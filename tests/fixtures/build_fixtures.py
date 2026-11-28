"""Build the two fixture scenarios for handoff H2: small, synthetic, deterministic.

These are NOT FaultLab runs (FaultLab v0 doesn't exist yet). They imitate FaultLab's six
services and four log formats (architecture §5 M0), so the real ingest path (format adapters,
redaction, Drain3) runs on them, and the pipeline has data with ground truth from day one.

  fx01  db_connection_pool_exhaustion in payment-svc; the alert fires on gateway, two hops
        away. Distractors: a notification-svc error burst and a catalog-svc warning spike.
  fx02  no fault: a short latency blip fires the alert on normal load. Correct output: abstain.

Gold templates are labelled by construction: the generator tags every line it emits because
of the fault, and gold = templates of tagged lines from the root service or its first-hop
neighbours (the rule the paired-run labeller will use, architecture §5 M0). The build fails
if a gold template also covers untagged lines.

Regenerate from the repo root, then commit the result:
    uv run python tests/fixtures/build_fixtures.py
tests/test_fixtures.py fails when the committed files differ from a fresh build, e.g. after
a masking or Drain3 change moved the template IDs.
"""

import argparse
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from triage.ingest.formats import SYSTEM_FORMATS
from triage.ingest.load import parse_logs
from triage.ingest.models import IngestConfig

OUT = Path(__file__).resolve().parent / "scenarios"
SYSTEM = "faultlab"
START = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
WARMUP, CLEAN, FAULT, RECOVERY, ALERT_OFFSET = 10, 65, 12, 5, 11  # minutes
F0 = WARMUP + CLEAN  # fault starts at minute 75
F1 = F0 + FAULT  # fault ends at minute 87
END = F1 + RECOVERY  # logs end at minute 92
ALERT = F0 + ALERT_OFFSET  # alert fires at minute 86

CALLS = {  # FaultLab call graph, caller -> callees (architecture §5 M0)
    "gateway": ["auth-svc", "catalog-svc", "cart-svc"],
    "cart-svc": ["payment-svc", "redis"],
    "catalog-svc": ["postgres"],
    "payment-svc": ["postgres", "notification-svc"],
}


def first_hop(service: str) -> set[str]:
    callers = {caller for caller, callees in CALLS.items() if service in callees}
    return set(CALLS.get(service, [])) | callers


# ---------- event model ----------
@dataclass(frozen=True)
class Rate:
    """Events per minute: `base` outside [start, end), `peak` inside, with a linear ramp."""

    base: float
    peak: float = 0.0
    start: float = 0.0
    end: float = 0.0
    ramp: float = 0.0

    def at(self, minute: float) -> float:
        if not self.start <= minute < self.end:
            return self.base
        if self.ramp and minute - self.start < self.ramp:
            return self.base + (self.peak - self.base) * (minute - self.start) / self.ramp
        return self.peak

    @property
    def max(self) -> float:
        return max(self.base, self.peak)


Body = Callable[[random.Random, float], Any]  # (rng, minute) -> str, or dict for nginx / kv


@dataclass(frozen=True)
class Kind:
    """One kind of log event a service emits."""

    service: str
    level: str  # DEBUG | INFO | WARN | ERROR
    rate: Rate
    body: Body
    logger: str = ""
    tag: str = "bg"  # bg | fault | symptom | distractor


def arrivals(rng: random.Random, rate: Rate) -> list[float]:
    """Poisson arrival minutes in [0, END), by thinning a process at the peak rate."""
    out: list[float] = []
    if rate.max <= 0:
        return out
    t = 0.0
    while True:
        t += rng.expovariate(rate.max)
        if t >= END:
            return out
        if rng.random() < rate.at(t) / rate.max:
            out.append(t)


# ---------- bodies ----------
def req(r: random.Random, method: str, path: str, status: int, rt: float) -> dict[str, Any]:
    size = r.randint(300, 5000) if status == 200 else r.randint(120, 200)
    return {"method": method, "path": path, "status": status, "rt": rt, "bytes": size}


def kv(msg: str, **fields: Any) -> dict[str, Any]:
    return {"msg": msg, "fields": fields}


def uid(r: random.Random) -> int:
    return r.randint(1000, 9999)


def order(r: random.Random) -> int:
    return r.randint(100000, 999999)


def cart(r: random.Random) -> int:
    return r.randint(1, 500)


def pool_stats(leaking: bool) -> Body:
    def body(r: random.Random, m: float) -> str:
        if leaking and F0 <= m < F1:
            active = min(20, 4 + int((m - F0) * 8))  # the leak empties the pool in ~2 minutes
            waiting = r.randint(3, 15) if active == 20 else 0
        else:
            active, waiting = r.randint(1, 5), 0
        return (
            f"HikariPool-1 - Pool stats (total=20, active={active}, idle={20 - active},"
            f" waiting={waiting})"
        )

    return body


def hikari_timeout(r: random.Random, m: float) -> str:
    msg = "HikariPool-1 - Connection is not available, request timed out after 5000ms."
    return "\n".join(
        [
            msg,
            f"java.sql.SQLTransientConnectionException: {msg}",
            "\tat com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)",
            "\tat com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:197)",
            "\tat com.shop.payment.ChargeService.charge(ChargeService.java:88)",
        ]
    )


def background(*, payments_failing: bool) -> list[Kind]:
    """Normal traffic for all six services, including notification-svc's harmless errors."""

    def ok(base: float) -> Rate:  # successful checkouts mostly stop while payments fail
        return Rate(base, base * 0.15, F0 + 2, F1) if payments_failing else Rate(base)

    return [
        # gateway: nginx access log
        Kind("gateway", "INFO", Rate(1.5), lambda r, m: req(
            r, "GET", f"/catalog/items?page={r.randint(1, 40)}", 200, r.uniform(0.01, 0.09))),
        Kind("gateway", "INFO", Rate(0.7), lambda r, m: req(
            r, "POST", f"/cart/{cart(r)}/items", 200, r.uniform(0.02, 0.12))),
        Kind("gateway", "INFO", ok(0.8), lambda r, m: req(
            r, "POST", "/checkout", 200, r.uniform(0.12, 0.45))),
        Kind("gateway", "INFO", Rate(0.5), lambda r, m: req(
            r, "GET", "/healthz", 200, r.uniform(0.001, 0.004))),
        Kind("gateway", "WARN", Rate(0.08), lambda r, m: req(
            r, "GET", f"/catalog/items/{r.randint(9000, 9999)}", 404, r.uniform(0.01, 0.03))),
        # auth-svc: Python logging
        Kind("auth-svc", "INFO", Rate(1.0), lambda r, m: (
            f"Token validated for user_id={uid(r)}"), "auth.sessions"),
        Kind("auth-svc", "INFO", Rate(0.3), lambda r, m: (
            f"Token cache miss for user_id={uid(r)}, fetching from store"), "auth.cache"),
        Kind("auth-svc", "WARN", Rate(0.05), lambda r, m: (
            f"Rejected expired token for user_id={uid(r)}"), "auth.sessions"),
        # catalog-svc: logback
        Kind("catalog-svc", "INFO", Rate(1.0), lambda r, m: (
            f"Served item list page={r.randint(1, 40)} size=20 in {r.randint(4, 60)}ms"),
            "c.s.catalog.ItemController"),
        Kind("catalog-svc", "INFO", Rate(0.1), lambda r, m: (
            f"Cache refresh completed: {r.randint(1900, 2100)} items in {r.randint(80, 400)}ms"),
            "c.s.catalog.ItemCache"),
        Kind("catalog-svc", "WARN", Rate(0.1), lambda r, m: (
            f"Slow query on items table took {r.randint(800, 2500)}ms"),
            "c.s.catalog.ItemRepository"),
        # cart-svc: key=value
        Kind("cart-svc", "INFO", Rate(0.7), lambda r, m: kv(
            "cart updated", cart_id=cart(r), items=r.randint(1, 9))),
        Kind("cart-svc", "INFO", Rate(0.2), lambda r, m: kv(
            "redis GET miss", key=f"cart:{cart(r)}")),
        Kind("cart-svc", "INFO", Rate(0.8), lambda r, m: kv(
            "checkout started", cart_id=cart(r))),
        Kind("cart-svc", "INFO", ok(0.8), lambda r, m: kv(
            "payment call ok", cart_id=cart(r), elapsed_ms=r.randint(60, 300))),
        # payment-svc: logback
        Kind("payment-svc", "INFO", ok(0.8), lambda r, m: (
            f"Charge authorized for order={order(r)} amount={r.uniform(5, 400):.2f}"),
            "c.s.payment.ChargeService"),
        Kind("payment-svc", "DEBUG", Rate(0.5), pool_stats(payments_failing),
             "com.zaxxer.hikari.pool.HikariPool"),
        Kind("payment-svc", "WARN", Rate(0.05), lambda r, m: (
            f"Retrying idempotent charge for order={order(r)} (attempt 2)"),
            "c.s.payment.ChargeService"),
        # notification-svc: Python logging, noisy by design (a permanent distractor)
        Kind("notification-svc", "ERROR", Rate(0.8), lambda r, m: (
            f"Failed to deliver email to user_id={uid(r)}: SMTP 451 temporary failure"),
            "notify.smtp"),
        Kind("notification-svc", "INFO", Rate(1.0), lambda r, m: (
            f"Queued notification order={order(r)} channel=email"), "notify.queue"),
        Kind("notification-svc", "WARN", Rate(0.4), lambda r, m: (
            f"Retry scheduled for notification id={r.randint(1, 99999)} in 30s"), "notify.queue"),
    ]  # fmt: skip


FX01_FAULT = [
    # Root cause: payment-svc stops returning pool connections at F0; the pool is empty ~2 min
    # later. Hikari's leak detector is the earliest signal (early onset).
    Kind("payment-svc", "WARN", Rate(0, 0.6, F0 + 0.5, F1), lambda r, m: (
        "Connection leak detection triggered for "
        f"org.postgresql.jdbc.PgConnection@{r.getrandbits(32):08x}, stack trace follows"),
        "com.zaxxer.hikari.pool.ProxyLeakTask", "fault"),
    Kind("payment-svc", "ERROR", Rate(0, 2.5, F0 + 2, F1, ramp=2), hikari_timeout,
         "com.zaxxer.hikari.pool.HikariPool", "fault"),
    Kind("payment-svc", "ERROR", Rate(0, 2.0, F0 + 2, F1, ramp=2), lambda r, m: (
        f"Charge failed for order={order(r)}: could not acquire DB connection"),
        "c.s.payment.ChargeService", "fault"),
    # First hop upstream: cart-svc sees payment-svc fail after its 5 s timeout.
    Kind("cart-svc", "ERROR", Rate(0, 2.0, F0 + 2.2, F1, ramp=2), lambda r, m: kv(
        "payment call failed", cart_id=cart(r), elapsed_ms=r.randint(5000, 5040),
        error="upstream returned 503"), tag="fault"),
    # Two hops away: the symptom the alert fires on. Not gold (not root or first hop).
    Kind("gateway", "ERROR", Rate(0, 1.5, F0 + 2.3, F1, ramp=2), lambda r, m: req(
        r, "POST", "/checkout", 504, r.uniform(5.0, 5.1)), tag="symptom"),
]  # fmt: skip

FX01_DISTRACTORS = [
    # noisy_template_burst: a loud, new error in notification-svc, unrelated to the fault
    Kind("notification-svc", "ERROR", Rate(0, 5.0, F0 + 5, F0 + 9), lambda r, m: (
        f"SMTP relay rate-limited, dropping batch of {r.randint(5, 40)} notifications"),
        "notify.smtp", "distractor"),
    # unrelated_warning_spike: a known warning in catalog-svc suddenly ~30x more frequent
    Kind("catalog-svc", "WARN", Rate(0, 3.0, F0 + 3, F0 + 8), lambda r, m: (
        f"Slow query on items table took {r.randint(800, 2500)}ms"),
        "c.s.catalog.ItemRepository", "distractor"),
]  # fmt: skip

FX02_BLIP = [
    # The false alarm: catalog pages are slow for ~3 minutes but succeed. Nothing is logged as
    # wrong (same template as normal traffic, only rt differs), so the logs cannot explain it.
    Kind("gateway", "INFO", Rate(0, 1.2, ALERT - 3, ALERT + 0.5), lambda r, m: req(
        r, "GET", f"/catalog/items?page={r.randint(1, 40)}", 200, r.uniform(2.1, 2.8)),
        tag="symptom"),
]  # fmt: skip

FX02_DISTRACTORS = [
    # unrelated_warning_spike: auth-svc rejects a wave of expired tokens
    Kind("auth-svc", "WARN", Rate(0, 2.5, F0 + 3, F0 + 9), lambda r, m: (
        f"Rejected expired token for user_id={uid(r)}"), "auth.sessions", "distractor"),
]  # fmt: skip


@dataclass(frozen=True)
class Fixture:
    id: str
    seed: int
    title: str
    symptom: str
    fault: dict[str, Any] | None
    distractors: list[dict[str, str]]
    kinds: list[Kind] = field(repr=False)


FIXTURES = [
    Fixture(
        id="fx01",
        seed=101,
        title="db connection pool exhaustion in payment-svc, alert on gateway",
        symptom="p99 latency > 2s on /checkout",
        fault={
            "type": "db_connection_pool_exhaustion",
            "root_service": "payment-svc",
            "injector": {"kind": "pool_leak", "params": {"connections": 20}},
        },
        distractors=[
            {"kind": "noisy_template_burst", "service": "notification-svc"},
            {"kind": "unrelated_warning_spike", "service": "catalog-svc"},
        ],
        kinds=background(payments_failing=True) + FX01_FAULT + FX01_DISTRACTORS,
    ),
    Fixture(
        id="fx02",
        seed=202,
        title="no fault: latency blip on normal load (false alarm, should abstain)",
        symptom="p99 latency > 2s on /catalog/items",
        fault=None,
        distractors=[{"kind": "unrelated_warning_spike", "service": "auth-svc"}],
        kinds=background(payments_failing=False) + FX02_BLIP + FX02_DISTRACTORS,
    ),
]


# ---------- rendering ----------
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
_PY_LEVEL = {"WARN": "WARNING", "FATAL": "CRITICAL"}


def _kv_value(value: Any) -> str:
    return f'"{value}"' if isinstance(value, str) and " " in value else str(value)


def render(fmt: str, service: str, ts: datetime, kind: Kind, body: Any, r: random.Random) -> str:
    ms = ts.microsecond // 1000
    if fmt == "faultlab.logback":
        thread = f"http-nio-8080-exec-{r.randint(1, 8)}"
        return f"{ts:%Y-%m-%d %H:%M:%S}.{ms:03d} [{thread}] {kind.level:<5} {kind.logger} - {body}"
    if fmt == "faultlab.python":
        level = _PY_LEVEL.get(kind.level, kind.level)
        return f"{ts:%Y-%m-%d %H:%M:%S},{ms:03d} {level} {kind.logger}: {body}"
    if fmt == "faultlab.nginx":
        stamp = f"{ts.day:02d}/{_MONTHS[ts.month - 1]}/{ts.year}:{ts:%H:%M:%S} +0000"
        client = f"10.0.{r.randint(0, 3)}.{r.randint(2, 250)}"
        request = f"{body['method']} {body['path']} HTTP/1.1"
        return (
            f'{client} - - [{stamp}] "{request}" {body["status"]} {body["bytes"]} "-" '
            f'"locust/2.31.8" rt={body["rt"]:.3f}'
        )
    if fmt == "faultlab.kv":
        host = f"{service.removesuffix('-svc')}-{r.randint(1, 2)}"
        fields = " ".join(f"{k}={_kv_value(v)}" for k, v in body["fields"].items())
        head = f"ts={ts:%Y-%m-%dT%H:%M:%S}.{ms:03d}Z level={kind.level.lower()} svc={service}"
        return f'{head} host={host} msg="{body["msg"]}" {fields}'.rstrip()
    raise ValueError(f"unknown format {fmt}")


def write_logs(fx: Fixture, out: Path) -> dict[tuple[str, int], str]:
    """Write logs/<service>.log; return {(source_file, line_no): tag} for every event."""
    rng = random.Random(fx.seed)
    events: dict[str, list[tuple[float, int, Kind, Any]]] = {}
    for k, kind in enumerate(fx.kinds):
        for minute in arrivals(rng, kind.rate):
            events.setdefault(kind.service, []).append((minute, k, kind, kind.body(rng, minute)))

    tags: dict[tuple[str, int], str] = {}
    (out / "logs").mkdir(parents=True, exist_ok=True)
    for service, fmt in SYSTEM_FORMATS[SYSTEM].items():
        source_file = f"logs/{service}.log"
        lines: list[str] = []
        for minute, _, kind, body in sorted(events.get(service, []), key=lambda e: e[:2]):
            ts = START + timedelta(minutes=minute)
            tags[(source_file, len(lines) + 1)] = kind.tag
            lines += render(fmt, service, ts, kind, body, rng).split("\n")
        (out / source_file).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return tags


def gold_templates(fx: Fixture, out: Path, tags: dict[tuple[str, int], str]) -> dict[str, str]:
    """{template_id: template} of fault-tagged lines from the root service and its first hop."""
    logs = parse_logs(out, SYSTEM, IngestConfig())
    if logs.unparsed_lines:
        raise RuntimeError(f"{fx.id}: {logs.unparsed_lines} unparsed lines")
    if fx.fault is None:
        return {}
    near = {fx.fault["root_service"]} | first_hop(fx.fault["root_service"])
    tag_of = {r.template_id: set() for r in logs.records}
    for r in logs.records:
        tag_of[r.template_id].add(tags[(r.source_file, r.line_no)])
    gold = {
        r.template_id: logs.templates[r.template_id]
        for r in logs.records
        if r.service in near and tags[(r.source_file, r.line_no)] == "fault"
    }
    impure = {t: sorted(tag_of[t]) for t in gold if tag_of[t] != {"fault"}}
    if impure:
        raise RuntimeError(f"{fx.id}: gold templates also cover non-fault lines: {impure}")
    return gold


def write_spec(fx: Fixture, out: Path, gold: dict[str, str]) -> None:
    def iso(minute: float) -> str:
        return (START + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")

    authored = {
        "id": fx.id,
        "system": SYSTEM,
        "seed": fx.seed,
        "timeline": {"warmup": f"{WARMUP}m", "clean": f"{CLEAN}m", "fault": f"{FAULT}m",
                     "recovery": f"{RECOVERY}m"},
        "alert": {"service": "gateway", "offset_after_fault_start": f"{ALERT_OFFSET}m",
                  "symptom": fx.symptom},
        "fault": fx.fault,
        "distractors": fx.distractors,
    }  # fmt: skip
    root_cause = (
        {"service": fx.fault["root_service"], "fault_type": fx.fault["type"]}
        if fx.fault
        else {"service": None, "fault_type": "unknown"}
    )
    tooling = {
        "run": {"started_at": iso(0), "alert_ts": iso(ALERT)},
        "gold": {
            "root_cause": root_cause,
            "should_abstain": fx.fault is None,
            "templates": sorted(gold),  # labelled by construction (see build_fixtures.py)
            "runbook_steps": [],  # filled by Member 3 after kb-v1 (H8)
        },
        "split": None,  # fixtures are not part of the dev/test benchmark
    }
    tail = yaml.safe_dump(tooling, sort_keys=False, default_flow_style=False, width=100)
    tail = re.sub(  # show each gold template's text next to its ID
        r"^(\s*- '?([0-9a-f]{8})'?)$", lambda m: f"{m[1]}  # {gold[m[2]]}", tail, flags=re.M
    )
    text = (
        f"# Fixture scenario {fx.id}: {fx.title}.\n"
        "# Synthetic, written by tests/fixtures/build_fixtures.py. Do not edit by hand.\n"
        + yaml.safe_dump(authored, sort_keys=False, default_flow_style=None, width=100)
        + "# --- filled by tooling, never by hand during authoring ---\n"
        + tail
    )
    (out / "scenario.yaml").write_text(text, encoding="utf-8", newline="\n")


def build(root: Path = OUT) -> None:
    for fx in FIXTURES:
        out = root / fx.id
        tags = write_logs(fx, out)
        write_spec(fx, out, gold_templates(fx, out, tags))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"output root (default {OUT})")
    args = parser.parse_args()
    build(args.out)
    for fx in FIXTURES:
        print(f"wrote {args.out / fx.id}")
