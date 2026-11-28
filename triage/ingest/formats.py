"""Format adapters: one parser per log format, registered by name (architecture §5 M1, step 1).

An adapter turns one raw line into a `ParsedLine`, or returns None when the line has no
header of its format (for example a stack-trace line, which ingest folds into the previous
record). FaultLab services log in deliberately different formats (architecture §5 M0); the
service → format map for each system lives in `SYSTEM_FORMATS`.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from http import HTTPStatus

from triage.ingest.models import ParsedLine

Adapter = Callable[[str, str], ParsedLine | None]  # (raw line, service) -> ParsedLine | None

ADAPTERS: dict[str, Adapter] = {}

# Which adapter parses which service's logs, per system. RCAEval systems are added here
# (or registered by their loader) as `rcaeval.<system>` adapters.
SYSTEM_FORMATS: dict[str, dict[str, str]] = {
    "faultlab": {
        "gateway": "faultlab.nginx",
        "auth-svc": "faultlab.python",
        "catalog-svc": "faultlab.logback",
        "cart-svc": "faultlab.kv",
        "payment-svc": "faultlab.logback",
        "notification-svc": "faultlab.python",
    },
}

_LEVELS = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "ERR": "ERROR",
    "ERROR": "ERROR",
    "CRITICAL": "FATAL",
    "FATAL": "FATAL",
}

_MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def register(name: str) -> Callable[[Adapter], Adapter]:
    def decorator(fn: Adapter) -> Adapter:
        if name in ADAPTERS:
            raise ValueError(f"format adapter {name!r} is already registered")
        ADAPTERS[name] = fn
        return fn

    return decorator


def format_for(system: str, service: str) -> str:
    try:
        return SYSTEM_FORMATS[system][service]
    except KeyError:
        raise KeyError(
            f"no log format known for service {service!r} of system {system!r}; "
            "add it to SYSTEM_FORMATS in triage/ingest/formats.py"
        ) from None


def parse_line(raw: str, service: str, system: str = "faultlab") -> ParsedLine | None:
    """Parse one line of `service`'s log (architecture §6.3 entry point)."""
    return ADAPTERS[format_for(system, service)](raw, service)


def normalize_level(level: str | None) -> str | None:
    if not level:
        return None
    up = level.upper()
    return _LEVELS.get(up, up)


# ---------- faultlab.logback ----------
# 2026-11-20 11:17:03.412 [http-nio-8080-exec-3] ERROR com.zaxxer.hikari.pool.HikariPool - msg
_LOGBACK = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \[(?P<thread>[^\]]*)\] "
    r"(?P<level>[A-Z]+) +(?P<logger>\S+) - (?P<msg>.*)$"
)


@register("faultlab.logback")
def _logback(raw: str, service: str) -> ParsedLine | None:
    m = _LOGBACK.match(raw)
    if not m:
        return None
    ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
    return ParsedLine(ts, service, None, normalize_level(m["level"]), m["msg"])


# ---------- faultlab.python ----------
# 2026-11-20 10:04:51,880 WARNING auth.sessions: Rejected expired token for user_id=4821
_PYTHON = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<level>[A-Z]+) "
    r"(?P<logger>[\w.]+): (?P<msg>.*)$"
)


@register("faultlab.python")
def _python(raw: str, service: str) -> ParsedLine | None:
    m = _PYTHON.match(raw)
    if not m:
        return None
    ts = datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=UTC)
    return ParsedLine(ts, service, None, normalize_level(m["level"]), m["msg"])


# ---------- faultlab.nginx ----------
# 10.0.2.17 - - [20/Nov/2026:11:21:40 +0000] "POST /checkout HTTP/1.1" 504 167 "-" "ua" rt=5.012
_NGINX = re.compile(
    r'^(?P<client>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) [^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-) "[^"]*" "[^"]*"(?: rt=(?P<rt>[\d.]+))?$'
)
_NGINX_TS = re.compile(
    r"^(?P<d>\d{2})/(?P<mon>[A-Za-z]{3})/(?P<y>\d{4}):(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2}) "
    r"(?P<sign>[+-])(?P<oh>\d{2})(?P<om>\d{2})$"
)


def _nginx_ts(text: str) -> datetime | None:
    m = _NGINX_TS.match(text)
    if not m or m["mon"] not in _MONTHS:
        return None
    offset = timedelta(hours=int(m["oh"]), minutes=int(m["om"]))
    tz = timezone(offset if m["sign"] == "+" else -offset)
    y, d, hh, mm, ss = (int(m[k]) for k in ("y", "d", "H", "M", "S"))
    return datetime(y, _MONTHS[m["mon"]], d, hh, mm, ss, tzinfo=tz).astimezone(UTC)


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Unknown"


@register("faultlab.nginx")
def _nginx(raw: str, service: str) -> ParsedLine | None:
    m = _NGINX.match(raw)
    if not m:
        return None
    ts = _nginx_ts(m["ts"])
    if ts is None:
        return None
    status = int(m["status"])
    level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
    # Drain3 routes on the first tokens, so method + path come first (one template family per
    # endpoint). Masking turns the status code into <*>; the reason phrase ("Gateway Timeout")
    # survives masking and keeps a 504 apart from a 200. Client IP / user agent stay in raw only.
    message = f"{m['method']} {m['path']} {status} {_reason(status)}"
    if m["rt"]:
        message += f" rt={m['rt']}"
    return ParsedLine(ts, service, None, level, message)


# ---------- faultlab.kv ----------
# ts=2026-11-20T11:18:09.551Z level=error svc=cart-svc host=cart-2 msg="payment call failed" a=1
_KV_PAIR = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')
_KV_HEADER = {"ts", "level", "svc", "host", "msg"}


@register("faultlab.kv")
def _kv(raw: str, service: str) -> ParsedLine | None:
    if not raw.startswith("ts="):
        return None
    pairs = _KV_PAIR.findall(raw)
    fields = dict(pairs)
    try:
        ts = datetime.fromisoformat(fields["ts"])
    except (KeyError, ValueError):
        return None
    ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    msg = fields.get("msg", "").strip('"')
    extras = " ".join(f"{k}={v}" for k, v in pairs if k not in _KV_HEADER)
    message = f"{msg} {extras}".strip()
    level = normalize_level(fields.get("level"))
    return ParsedLine(ts, service, fields.get("host"), level, message)
