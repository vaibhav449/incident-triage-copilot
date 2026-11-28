"""Scenario folders: find one, read the pipeline-safe part of its `scenario.yaml`, list its logs.

`scenario.yaml` holds more than the `gold:` block that could give the answer away:
- `fault:` names the fault type and root service,
- `distractors:` names the decoy services,
- `timeline:` and `alert.offset_after_fault_start` together give the exact fault start.

So the pipeline does not get "everything except gold". It gets an **allowlist**: the
scenario id, the system and the alert as an operator would see it (service, symptom,
severity, time). That is what goes into `scenarios.spec`, which `triage_rw` can read.
Only `triage/gold/` and `triage/eval/` read the rest.
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_ROOTS = (REPO_ROOT / "data" / "scenarios", REPO_ROOT / "tests" / "fixtures" / "scenarios")
SPEC_FILE = "scenario.yaml"


def resolve(ref: str | Path) -> Path:
    """Scenario folder for a folder path or a scenario id (looked up in SCENARIO_ROOTS)."""
    path = Path(ref)
    if (path / SPEC_FILE).is_file():
        return path.resolve()
    for root in SCENARIO_ROOTS:
        if (root / str(ref) / SPEC_FILE).is_file():
            return root / str(ref)
    roots = ", ".join(str(r.relative_to(REPO_ROOT)) for r in SCENARIO_ROOTS)
    raise FileNotFoundError(f"no scenario {ref!r}: not a folder with {SPEC_FILE}, not in {roots}")


def read_yaml(scenario_dir: Path) -> dict[str, Any]:
    with (scenario_dir / SPEC_FILE).open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or "id" not in doc or "system" not in doc:
        raise ValueError(f"{scenario_dir / SPEC_FILE}: needs at least `id` and `system`")
    return doc


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def pipeline_spec(doc: dict[str, Any]) -> dict[str, Any]:
    """The part of scenario.yaml the pipeline may see (stored in `scenarios.spec`)."""
    alert = doc.get("alert") or {}
    run = doc.get("run") or {}
    return {
        "id": doc["id"],
        "system": doc["system"],
        "alert": {
            "service": alert.get("service"),
            "symptom": alert.get("symptom"),
            "severity": alert.get("severity", "high"),
            "ts": _iso(run.get("alert_ts")),  # written by the scenario runner
        },
    }


def split_of(doc: dict[str, Any]) -> str | None:
    """`split` is set by `triage split assign`, never by hand."""
    return doc.get("split")


def log_files(scenario_dir: Path) -> list[Path]:
    """`logs/<service>.log`, sorted. (Compressed `*.log.zst` support comes with FaultLab.)"""
    return sorted((scenario_dir / "logs").glob("*.log"))
