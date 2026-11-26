"""`triage` command-line entry point.

Nobody edits this file to add commands, so the three of us never conflict here.
To give your module CLI commands, create `triage/<your_package>/cli.py` with:

    import typer

    kb_app = typer.Typer(help="Knowledge base commands.")

    @kb_app.command()
    def build() -> None:
        ...

    def register(app: typer.Typer) -> None:
        app.add_typer(kb_app, name="kb")   # -> `triage kb build`
        # or a top-level command:  app.command("run")(run)  -> `triage run`

It is picked up automatically. Two packages registering the same command name is an
error, so nobody can silently shadow a teammate's command. Import heavy libraries
(torch, transformers, ...) inside your command functions, not at module top, so that
`triage --help` stays fast.
"""

import importlib
import pkgutil
from types import ModuleType

import typer

import triage

app = typer.Typer(no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Incident-Triage Copilot: evidence-grounded root-cause analysis."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(triage.__version__)


def _command_names(root: typer.Typer) -> list[str]:
    names = [
        info.name or info.callback.__name__.replace("_", "-")
        for info in root.registered_commands
        if info.callback is not None or info.name
    ]
    names += [
        info.name or info.typer_instance.info.name
        for info in root.registered_groups
        if info.name or info.typer_instance.info.name
    ]
    return names


def _assert_unique(root: typer.Typer) -> None:
    names = _command_names(root)
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise RuntimeError(f"Duplicate `triage` command names: {', '.join(dupes)}")


def discover(root: typer.Typer = app, package: ModuleType = triage) -> list[str]:
    """Import every `<package>/<sub>/cli.py` and call its `register(root)`."""
    loaded = []
    for mod in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if not mod.ispkg:
            continue
        module_name = f"{package.__name__}.{mod.name}.cli"
        try:
            cli_module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue  # this package has no CLI (yet)
            raise
        cli_module.register(root)
        loaded.append(mod.name)
    _assert_unique(root)
    return loaded


def main() -> None:
    discover()
    app()
