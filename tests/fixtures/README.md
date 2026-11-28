# Fixture scenarios (handoff H2)

> **Member 2: don't open this folder until `kb-v1` is tagged** (anti-leakage rule, work-distribution §11).

Two small **synthetic** scenarios for smoke tests and stubs. They are not FaultLab runs: `build_fixtures.py` generates them, imitating FaultLab's six services and four log formats. Timeline: 92 minutes from 2026-11-20 10:00 UTC, with the alert at 11:26.

| ID | What happens | Correct output |
|---|---|---|
| `fx01` | `db_connection_pool_exhaustion` in payment-svc. The alert fires on gateway (two hops away). Distractors: a notification-svc error burst and a catalog-svc warning spike. | payment-svc · db_connection_pool_exhaustion. 4 gold templates |
| `fx02` | No fault. A short latency blip on `/catalog/items` fires the alert on normal load. Distractor: an auth-svc warning spike. | abstain (`should_abstain: true`) |

**Load them** (Postgres up and migrated):

```bash
make db-up && make db-migrate
make fixtures        # = triage ingest fx01 fx02 && triage gold load fx01 fx02
```

**Gold** is labelled by construction: every line emitted because of the fault is tagged, and gold templates are the templates of tagged lines from the root service or its first-hop neighbours. Each gold template ID in `scenario.yaml` has its text next to it as a comment. `runbook_steps` stays empty until Member 3 labels them after `kb-v1` (H8). `split` is null because fixtures are not part of the dev/test benchmark.

**Regenerate** after changing the builder, masking or Drain3 settings (template IDs move), then commit:

```bash
uv run python tests/fixtures/build_fixtures.py
```

`tests/test_fixtures.py` fails when the committed files differ from a fresh build.
