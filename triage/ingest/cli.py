"""CLI commands owned by Member 1. Discovered automatically by `triage/cli.py`."""

import psycopg
import typer

from triage.ingest.db import admin_dsn
from triage.ingest.migrate import apply_migrations, ensure_roles, status

db_app = typer.Typer(help="Database schema, roles and migrations.", no_args_is_help=True)


def _admin_connection() -> psycopg.Connection:
    try:
        return psycopg.connect(admin_dsn(), autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        typer.echo(f"Cannot reach Postgres: {exc}\nIs it running? Try `make db-up`.", err=True)
        raise typer.Exit(1) from exc


@db_app.command()
def migrate() -> None:
    """Create/update the triage roles and apply pending migrations."""
    with _admin_connection() as conn:
        ensure_roles(conn)
        applied = apply_migrations(conn)
    typer.echo(f"applied: {', '.join(applied)}" if applied else "up to date")


@db_app.command("status")
def show_status() -> None:
    """List migrations and whether each one is applied."""
    with _admin_connection() as conn:
        rows = status(conn)
    for version, applied in rows:
        typer.echo(f"{version:<20} {'applied' if applied else 'PENDING'}")


def register(app: typer.Typer) -> None:
    app.add_typer(db_app, name="db")
