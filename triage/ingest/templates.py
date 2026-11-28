"""Template mining with Drain3 (architecture §5 M1, step 3).

A cluster's template can still change while lines arrive, so template IDs are assigned only
after every line of the scenario has been mined: `template_id = sha1(final template)[:8]`.
Each scenario gets a fresh miner, so its IDs do not depend on what was ingested before it.
"""

import hashlib
from collections.abc import Sequence

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from triage.ingest.masking import drain_masking_instructions, normalize_template
from triage.ingest.models import IngestConfig, LogRecord


class TemplateCollisionError(RuntimeError):
    """Two different template texts share the same 8-hex-digit ID."""


def template_id(template: str) -> str:
    return hashlib.sha1(template.encode("utf-8")).hexdigest()[:8]


def new_miner(cfg: IngestConfig) -> TemplateMiner:
    config = TemplateMinerConfig()  # never let Drain3 look for a drain3.ini in the cwd
    config.drain_depth = cfg.drain_depth
    config.drain_sim_th = cfg.drain_sim_th
    config.drain_max_children = cfg.drain_max_children
    config.masking_instructions = drain_masking_instructions()
    config.mask_prefix, config.mask_suffix = "<", ">"
    config.parametrize_numeric_tokens = True
    return TemplateMiner(persistence_handler=None, config=config)


def mine(records: Sequence[LogRecord], cfg: IngestConfig) -> dict[str, str]:
    """Set `template_id` (and `params`) on every record in place.

    Returns `{template_id: template}` for the templates used. Records are mined in the
    order given; callers pass them sorted by time so the result is deterministic.
    """
    miner = new_miner(cfg)
    cluster_ids = [miner.add_log_message(r.message)["cluster_id"] for r in records]

    templates: dict[str, str] = {}
    final: dict[int, tuple[str, str]] = {}  # cluster_id -> (template_id, typed template)
    for cluster in miner.drain.clusters:
        typed = cluster.get_template()
        text = normalize_template(typed)
        tid = template_id(text)
        if templates.setdefault(tid, text) != text:
            raise TemplateCollisionError(f"{tid}: {templates[tid]!r} vs {text!r}")
        final[cluster.cluster_id] = (tid, typed)

    for record, cid in zip(records, cluster_ids, strict=True):
        tid, typed = final[cid]
        record.template_id = tid
        if cfg.extract_params:
            extracted = miner.extract_parameters(typed, record.message, exact_matching=True)
            record.params = None if extracted is None else [p.value for p in extracted]
    return templates
