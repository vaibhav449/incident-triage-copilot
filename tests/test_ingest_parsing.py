"""M1 unit tests that need no database: format adapters, redaction, masking, Drain3 mining."""

from datetime import UTC, datetime

import pytest

from triage.ingest.formats import ADAPTERS, normalize_level, parse_line
from triage.ingest.masking import REDACTED, normalize_template, redact
from triage.ingest.models import IngestConfig, LogRecord
from triage.ingest.templates import mine, template_id

# ---------- format adapters ----------


def test_logback_line():
    raw = (
        "2026-11-20 11:17:03.412 [http-nio-8080-exec-3] ERROR com.zaxxer.hikari.pool.HikariPool"
        " - Connection is not available"
    )
    p = parse_line(raw, "payment-svc")
    assert p.ts == datetime(2026, 11, 20, 11, 17, 3, 412000, tzinfo=UTC)
    assert (p.service, p.host, p.level) == ("payment-svc", None, "ERROR")
    assert p.message == "Connection is not available"


def test_python_line_level_names_are_normalized():
    raw = "2026-11-20 10:04:51,880 WARNING auth.sessions: Rejected expired token for user_id=4821"
    p = parse_line(raw, "auth-svc")
    assert p.ts == datetime(2026, 11, 20, 10, 4, 51, 880000, tzinfo=UTC)
    assert p.level == "WARN"
    assert p.message == "Rejected expired token for user_id=4821"


def test_nginx_line_level_from_status_and_timezone_converted():
    raw = (
        '10.0.2.17 - - [20/Nov/2026:16:51:40 +0530] "POST /checkout HTTP/1.1" 504 167 "-"'
        ' "locust/2.31.8" rt=5.012'
    )
    p = parse_line(raw, "gateway")
    assert p.ts == datetime(2026, 11, 20, 11, 21, 40, tzinfo=UTC)
    assert p.level == "ERROR"
    assert p.message == "POST /checkout 504 Gateway Timeout rt=5.012"
    assert parse_line(raw.replace(" 504 ", " 404 "), "gateway").level == "WARN"
    assert parse_line(raw.replace(" 504 ", " 200 "), "gateway").level == "INFO"


def test_kv_line_keeps_extra_fields_in_the_message():
    raw = (
        "ts=2026-11-20T11:18:09.551Z level=error svc=cart-svc host=cart-2"
        ' msg="payment call failed" cart_id=7 error="upstream returned 503"'
    )
    p = parse_line(raw, "cart-svc")
    assert p.ts == datetime(2026, 11, 20, 11, 18, 9, 551000, tzinfo=UTC)
    assert (p.host, p.level) == ("cart-2", "ERROR")
    assert p.message == 'payment call failed cart_id=7 error="upstream returned 503"'


@pytest.mark.parametrize("fmt", sorted(ADAPTERS))
def test_lines_without_a_header_return_none(fmt):
    line = "\tat com.shop.payment.ChargeService.charge(ChargeService.java:88)"
    assert ADAPTERS[fmt](line, "x") is None


def test_unknown_service_error_says_where_to_add_it():
    with pytest.raises(KeyError, match="SYSTEM_FORMATS"):
        parse_line("anything", "no-such-svc")


def test_normalize_level():
    assert [normalize_level(x) for x in ("warning", "CRITICAL", "err", "Info", None)] == [
        "WARN",
        "FATAL",
        "ERROR",
        "INFO",
        None,
    ]


# ---------- redaction and masking ----------


def test_redact_removes_secrets_and_keeps_ordinary_values():
    assert redact("login failed password=hunter2 user=bob") == (
        f"login failed password={REDACTED} user=bob"
    )
    assert redact("Authorization: Bearer eyJhbGc.eyJzdWI.sig") == f"Authorization: {REDACTED}"
    assert redact("calling with bearer abc.def-123") == f"calling with bearer {REDACTED}"
    assert redact('api_key="two words" next') == f"api_key={REDACTED} next"
    assert redact("Token validated for user_id=4821") == "Token validated for user_id=4821"


def test_redact_card_numbers_only_when_luhn_valid():
    assert redact("card 4111 1111 1111 1111 declined") == f"card {REDACTED} declined"
    assert redact("card 4111-1111-1111-1112 declined") == "card 4111-1111-1111-1112 declined"
    assert redact("order=1234567 trace=20261120111703") == "order=1234567 trace=20261120111703"


def test_normalize_template_only_touches_our_masks():
    assert normalize_template("took <DUR> for <NUM> from <IP>") == "took <*> for <*> from <*>"
    assert normalize_template("render <html> tag") == "render <html> tag"


# ---------- Drain3 mining ----------


def _rec(message: str, line_no: int) -> LogRecord:
    ts = datetime(2026, 11, 20, 10, 0, line_no, tzinfo=UTC)
    return LogRecord(ts, "svc", None, "INFO", message, message, "logs/svc.log", line_no)


def test_mine_masks_variables_and_ids_templates_by_text():
    recs = [
        _rec(f"Timeout after {n}ms talking to 10.0.0.{n}", i) for i, n in enumerate((5, 17, 230), 1)
    ]
    recs.append(_rec("Cache warmed", 4))
    templates = mine(recs, IngestConfig())

    tid = recs[0].template_id
    assert {r.template_id for r in recs[:3]} == {tid}
    assert templates[tid] == "Timeout after <*> talking to <*>"
    assert tid == template_id("Timeout after <*> talking to <*>")
    assert recs[1].params == ["17ms", "10.0.0.17"]
    assert templates[recs[3].template_id] == "Cache warmed"
    assert recs[3].params == []


def test_mine_is_deterministic():
    def run() -> list[str | None]:
        recs = [_rec(f"user {i} logged in from host-{i % 3}", i) for i in range(1, 30)]
        mine(recs, IngestConfig())
        return [r.template_id for r in recs]

    assert run() == run()
