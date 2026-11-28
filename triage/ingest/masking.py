"""Secret redaction (raw lines) and Drain3 masking (templates) — architecture §5 M1, step 2.

Two different jobs:
- `redact()` removes secrets and card-like numbers from the **raw** line before it is stored.
  Everything else in the raw line is kept, so `L:` citations stay meaningful.
- `MASKS` tell Drain3 which variable parts (IPs, UUIDs, numbers, ...) to ignore while
  clustering. The masks are typed while mining (more accurate parameter extraction) and
  `normalize_template()` turns them into `<*>` in the stored template, matching Loghub-2.0.
"""

import re

from drain3.masking import MaskingInstruction

# Order matters: the first pattern that matches a span wins.
MASKS: list[tuple[str, str]] = [
    ("UUID", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    ("TS", r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    ("EMAIL", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    ("IP", r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?\b"),
    # 0x1f, long hex ids (trace ids, hashes), and Java identity hashes like PgConnection@1a2b3c4d
    ("HEX", r"\b0x[0-9a-fA-F]+\b|\b(?=[0-9a-f]*\d)[0-9a-f]{12,}\b|(?<=@)[0-9a-f]{6,16}\b"),
    ("DUR", r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?:ms|us|ns|s|m|h)\b"),
    ("NUM", r"(?<![A-Za-z0-9.])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9])"),
]

_MASK_TOKEN = re.compile("<(?:" + "|".join(name for name, _ in MASKS) + ")>")

_SECRET_KV = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)"
    r"(\s*[=:]\s*)((?:bearer\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+))"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

REDACTED = "<REDACTED>"


def drain_masking_instructions() -> list[MaskingInstruction]:
    return [MaskingInstruction(pattern, name) for name, pattern in MASKS]


def normalize_template(template: str) -> str:
    """Typed Drain3 masks (`<NUM>`, `<IP>`, ...) → `<*>`."""
    return _MASK_TOKEN.sub("<*>", template)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match[0])
    return REDACTED if 13 <= len(digits) <= 19 and _luhn_ok(digits) else match[0]


def redact(raw: str) -> str:
    """Remove secrets (passwords, tokens, keys, bearer tokens) and card-like numbers."""
    raw = _SECRET_KV.sub(lambda m: f"{m[1]}{m[2]}{REDACTED}", raw)
    raw = _BEARER.sub(lambda m: f"{m[1]} {REDACTED}", raw)
    return _CARD.sub(_card, raw)
