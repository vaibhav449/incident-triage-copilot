"""Database connection settings for the three roles (architecture §7.1).

Values come from the environment (`.env`, loaded by `make` via `uv run --env-file`).
If a variable is unset, the `.env.example` development default is used, so a fresh
checkout works against `make db-up` with no configuration.
"""

import os
from typing import Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

Role = Literal["rw", "ro", "eval"]

ROLE_NAMES: dict[Role, str] = {"rw": "triage_rw", "ro": "triage_ro", "eval": "triage_eval"}

_DEFAULTS = {
    "DATABASE_URL_ADMIN": "postgresql://triage_admin:change-me@localhost:5432/triage",
    "DATABASE_URL_RW": "postgresql://triage_rw:change-me@localhost:5432/triage",
    "DATABASE_URL_RO": "postgresql://triage_ro:change-me@localhost:5432/triage",
    "DATABASE_URL_EVAL": "postgresql://triage_eval:change-me@localhost:5432/triage",
}


def _url(var: str, dbname: str | None) -> str:
    url = os.environ.get(var) or _DEFAULTS[var]
    if dbname is None:
        return url
    return make_conninfo(url, dbname=dbname)


def admin_dsn(dbname: str | None = None) -> str:
    """Superuser DSN, used only by `triage db migrate` and tests."""
    return _url("DATABASE_URL_ADMIN", dbname)


def dsn(role: Role, dbname: str | None = None) -> str:
    """DSN for one of the application roles."""
    return _url(f"DATABASE_URL_{role.upper()}", dbname)


def role_password(role: Role) -> str:
    """Password embedded in a role's DSN (used to create/update the role)."""
    password = conninfo_to_dict(dsn(role)).get("password")
    if not password:
        raise ValueError(f"DATABASE_URL_{role.upper()} has no password")
    return str(password)


def connect(role: Role, dbname: str | None = None, **kwargs) -> psycopg.Connection:
    return psycopg.connect(dsn(role, dbname), **kwargs)
