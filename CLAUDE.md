# CLAUDE.md — Incident-Triage Copilot

Shared context for every Claude Code session in this repo. Three students work here at the same time, so follow these rules exactly. Personal notes (who you are, your preferences) go in `CLAUDE.local.md`, which is gitignored. Never put them here.

## Project

An on-demand copilot that explains one alert at a time:
1. It shrinks millions of log lines into a small **evidence pack** by *counting* log templates. Logs are never embedded.
2. It retrieves matching **runbook steps**.
3. An LLM ranks likely causes, **citing an ID for every claim**.
4. Only claims that pass a **verifier** reach the engineer. If the evidence is too weak, the system abstains.

This is an NLP course project at IIIT Raichur.

| Read before working on… | Doc |
|---|---|
| any module, schema, metric or data format | `docs/01-master-architecture.md` (read the relevant section, not the whole file) |
| who owns what, the weekly plan, gates, anti-leakage rules | `docs/02-work-distribution.md` |

**Status (2026-11-25):** the repo skeleton is in place:
- `pyproject.toml` + `uv.lock`
- `Makefile`
- `docker-compose.yml` (Postgres only)
- CI
- one empty package per module under `triage/`

There is no module code yet. `make demo` arrives at Gate 4. Whoever changes a command updates this file in the same PR.

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python ≥ 3.11 |
| Package manager | **uv** — `pyproject.toml` + `uv.lock` (no pip/requirements.txt, no conda) |
| Backend / CLI | FastAPI, Pydantic v2, Typer (`triage` CLI) |
| UI | Streamlit |
| Storage | PostgreSQL 16 (logs, template counts, KB chunks) · FAISS + rank-bm25 (runbooks only) |
| NLP / ML | Drain3, HF Transformers, sentence-transformers, LLM behind `LLMClient` (hosted API or local) |
| Quality | ruff (lint + format), pytest |
| Infra | Docker Compose, GitHub Actions |

## Commands

```bash
# install (first time: install uv from https://docs.astral.sh/uv/)
uv sync                                        # create .venv and install exactly what uv.lock pins
cp .env.example .env                           # first time only, then fill in values

# run (dev)
docker compose up -d postgres                  # database
uv run uvicorn triage.api.main:app --reload    # API  → http://localhost:8000/docs
uv run streamlit run ui/app.py                 # UI   → http://localhost:8501
uv run triage --help                           # CLI: ingest, run, eval, kb build, split …

# lint / test / build
uv run ruff check .                            # lint
uv run ruff format --check .                   # format check (no rewriting of other files)
uv run pytest -q                               # tests
docker compose build                           # build check, only when Dockerfiles/compose changed
make check                                     # = the three lint/test commands above; run before finishing ANY task
make demo                                      # full stack: ingest demo scenarios, build KB, open the UI
```

`make help` lists every target, and `make db-up` / `make dev-api` / `make dev-ui` wrap the run commands above. Python 3.11 is pinned in `.python-version`; uv downloads it automatically.

## Who owns what

Work inside your own area. Names follow `docs/02-work-distribution.md` §1. Tell Claude which member you are in your `CLAUDE.local.md` (e.g. `I am Member 2 (Sourav).`). If you don't know which member you're working with, ask once.

| Area | Paths | Owner | Reviewer |
|---|---|---|---|
| Data & log pipeline (M0–M2), query tools, API, UI, Docker | `apps/faultlab/` `data/scenarios/` `data/splits/` `triage/ingest/` `triage/reduce/` `triage/reason/tools.py` `triage/api/` `ui/` `docker-compose.yml` `Makefile` | Member 1 — Vaibhav | Member 3 |
| NLP models & knowledge (M3–M4) | `kb/` `triage/nlp/` `triage/kb/` `data/labels/ner/` | Member 2 — Sourav | Member 1 (`kb/` content: Member 3) |
| LLM, verifier, evaluation (M5–M6), CI | `triage/reason/` (not `tools.py`) `triage/verify/` `triage/pipeline.py` `triage/config.py` `configs/` `triage/eval/` `.github/` | Member 3 — Satyajeet | Member 2 |
| **Shared contract** | `triage/schemas.py`, fault taxonomy | all three | all 3 must approve |
| Shared team setup | `CLAUDE.md` `.claude/commands/` `.gitignore` `.env.example` `docs/` | all three | any 1 |

## Project invariants — never break these

1. **Logs are counted, never embedded.** Only runbooks and postmortems go into the vector index.
2. **`triage/schemas.py` is a frozen contract.** It changes only in a PR labelled `contract-change`, approved by all three, with `SCHEMA_VERSION` bumped. If a task seems to need a schema change, stop and say so.
3. **Pipeline code never reads ground truth.** No access to the `gold` block of `scenario.yaml` or the `scenario_gold` table outside `triage/eval/` and `triage gold label`.
4. **Never run the test split.** Never run `triage eval --split test` or `--final`. Tune only on `dev`. The test split runs once, at Gate 5.
5. **Runbooks are written blind.** In `kb/runbooks/`, never add FaultLab service IDs (`payment-svc`, `cart-svc`, …), scenario IDs, or text copied from scenario logs. After `kb-v1`, existing runbooks are append-only; log edits in `kb/CHANGELOG.md`.
6. **Every LLM claim carries citation IDs** (`T:` `L:` `M:` `R:` `P:`). Never weaken the verifier to make a test pass.
7. **Query tools are read-only** (`triage_ro` DB role). Never give the LLM write, shell or network tools.
8. **Numbers come from `triage eval` only.** Report results only from runs with a committed config, never from notebooks.

## Vibe-coding guardrails

- **Stay in scope.** Never refactor, rename or reformat files unrelated to the current task, even if ruff would change them. If you notice a problem elsewhere, mention it; don't fix it.
- **Keep changes modular and isolated** so teammates aren't editing the same files at once.
  - Stay inside the current member's area (table above).
  - If a task needs edits in a teammate's area or a shared file, stop and list the files and the reason before editing.
  - Prefer adding a new file or function over rewriting a shared one.
  - **CLI commands:** never edit `triage/cli.py` to add one. Create `triage/<your_package>/cli.py` with a `register(app)` function and it is discovered automatically (example in the `triage/cli.py` docstring).
- **No new dependencies without confirmation.** First state the package, why it's needed, and the alternative you considered, then wait for an explicit yes.
  - Add with `uv add <pkg>` (or `uv add --dev <pkg>`). This updates `pyproject.toml` and `uv.lock` together.
  - Never hand-edit `uv.lock`.
- **Check before finishing.** Run `make check` before saying a task is done, plus `docker compose build` if Docker files changed.
  - Report the real result.
  - Fix failures your change caused.
  - Report pre-existing failures in files you didn't touch, without fixing them.
- **Never commit secrets or generated files.**
  - No `.env`, keys, tokens or passwords.
  - No generated data (`artifacts/`, `runs/`, scenario logs, model weights).
  - No `uv.lock` changes unless a dependency was intentionally added in this task.
  - New env vars go into `.env.example` with a placeholder and a one-line comment.
- **Don't read `.env` into the conversation.** Refer to variables by name only.

## Git & collaboration rules

- **NEVER commit or push directly to `main`.** Never force-push `main`.
- Destructive commands — `git reset --hard`, `git clean`, `git checkout -- .`, `git push --force` — need explicit confirmation first. On your own branch, use `--force-with-lease`, never `--force`.
- **Branches:** `<type>/<short-name>`, kebab-case, at most 4 words.
  - Types: `feat` `fix` `chore` `docs` `test` `refactor` `style`.
  - Examples: `feat/evidence-pack`, `fix/drain3-masking`, `docs/runbook-format`.
- **Commits:** short Conventional Commits, imperative mood, subject ≤ 72 chars.
  - Optional scope = module folder: `feat(reduce): add early-onset score`, `fix(api): handle missing pack id`, `chore: bump ruff`.
- **No AI attribution:** never add `Co-Authored-By: Claude …` trailers to commits, or "Generated with Claude Code" lines to PRs. `.claude/settings.json` turns this off for everyone, so don't override it.
- **Staging:** stage files by explicit path. Never `git add -A` or `git add .`.
- **PRs:** small, one feature or fix, into `main`. Request the reviewer from the ownership table. CI must be green before merge.
- **Stay current:** run `/sync` at least daily and always before opening a PR.

## Team slash commands (`.claude/commands/`)

| Command | Use it to |
|---|---|
| `/start-task <type> <description>` | Get a clean tree, update `main`, create `<type>/<short-name>` |
| `/ship [note]` | Run checks, review the diff for unrelated files or secrets, commit, push, print a PR description |
| `/sync` | Bring `origin/main` into your branch and resolve conflicts without losing anyone's work |
| `/handoff` | Print a 5-line update for the team group chat |
