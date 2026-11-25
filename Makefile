# Team entry points. `make check` must pass before every /ship.
.PHONY: help install check lint test db-up db-down dev-api dev-ui demo

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

install:         ## install exactly what uv.lock pins (creates .venv)
	uv sync

check: lint test ## lint + format check + tests — run before finishing ANY task

lint:            ## ruff lint and format check (never rewrites files)
	uv run ruff check .
	uv run ruff format --check .

test:            ## run the test suite
	uv run pytest -q

db-up:           ## start PostgreSQL 16 in Docker
	docker compose up -d postgres

db-down:         ## stop the database (data volume is kept)
	docker compose down

dev-api:         ## API dev server → http://localhost:8000/docs
	uv run uvicorn triage.api.main:app --reload

dev-ui:          ## Streamlit UI → http://localhost:8501
	uv run streamlit run ui/app.py

demo:            ## full stack demo (arrives at Gate 4)
	@echo "make demo is not implemented yet (Gate 4, Member 1)." && exit 1
