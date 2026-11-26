"""FastAPI application. Run with `make dev-api`."""

from fastapi import FastAPI

import triage

app = FastAPI(title="Incident-Triage Copilot", version=triage.__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
