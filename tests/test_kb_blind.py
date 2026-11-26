"""Anti-leakage guard: runbooks must be written blind to FaultLab.

See docs/02-work-distribution.md §11, rule 3. Generic words such as "gateway" are fine;
FaultLab service identifiers and scenario IDs are not.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNBOOKS = REPO / "kb" / "runbooks"
FORBIDDEN = re.compile(r"\b(?:auth|catalog|cart|payment|notification)-svc\b|\bs\d{3}-[a-z0-9-]+")


def test_runbooks_do_not_name_faultlab_services_or_scenarios():
    if not RUNBOOKS.exists():
        return
    offenders = [
        f"{path.relative_to(REPO)}: {match.group(0)}"
        for path in sorted(RUNBOOKS.rglob("*.md"))
        for match in FORBIDDEN.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, "Runbooks must stay blind to FaultLab:\n" + "\n".join(offenders)
