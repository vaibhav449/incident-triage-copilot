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


def ingest(
    scenarios: list[str] = typer.Argument(..., help="Scenario ids or scenario folders."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse only; don't touch the DB."),
) -> None:
    """Parse scenario logs (adapters, redaction, Drain3) and bulk-load them into Postgres."""
    import time

    from triage.ingest.load import ingest_scenario, parse_scenario, report

    for ref in scenarios:
        try:
            if dry_run:
                started = time.perf_counter()
                rep = report(parse_scenario(ref), 0, time.perf_counter() - started)
            else:
                rep = ingest_scenario(ref)
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        except psycopg.OperationalError as exc:
            typer.echo(f"Cannot reach Postgres: {exc}\nTry `make db-up db-migrate`.", err=True)
            raise typer.Exit(1) from exc
        new = "" if dry_run else f" ({rep.new_templates} new)"
        typer.echo(
            f"{rep.scenario_id}: {rep.files} files, {rep.source_lines} lines -> "
            f"{rep.records} records, {rep.templates} templates{new}, "
            f"{rep.continuation_lines} continuation, {rep.unparsed_lines} unparsed, "
            f"{rep.seconds:.2f}s" + (" [dry run]" if dry_run else "")
        )


def register(app: typer.Typer) -> None:
    app.add_typer(db_app, name="db")
    app.command("ingest")(ingest)
