"""`triage gold ...` commands (owner: Member 1). Discovered automatically by `triage/cli.py`."""

import psycopg
import typer

gold_app = typer.Typer(help="Ground-truth labels (connects as triage_eval).", no_args_is_help=True)


@gold_app.command()
def load(
    scenarios: list[str] = typer.Argument(..., help="Scenario ids or scenario folders."),
) -> None:
    """Copy each scenario's `gold:` block into `scenario_gold`. Ingest the scenario first."""
    from triage.gold.load import gold_of, load_gold
    from triage.ingest import db

    try:
        with db.connect("eval", connect_timeout=5) as conn:
            for ref in scenarios:
                scenario_id, gold = gold_of(ref)
                try:
                    load_gold(conn, scenario_id, gold)
                except psycopg.errors.ForeignKeyViolation as exc:
                    typer.echo(f"{scenario_id}: not ingested yet; run `triage ingest`.", err=True)
                    raise typer.Exit(1) from exc
                typer.echo(f"{scenario_id}: gold loaded")
    except psycopg.OperationalError as exc:
        typer.echo(f"Cannot reach Postgres: {exc}\nTry `make db-up db-migrate`.", err=True)
        raise typer.Exit(1) from exc
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


def register(app: typer.Typer) -> None:
    app.add_typer(gold_app, name="gold")
