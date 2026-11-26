import importlib
import sys

import pytest
import typer
from typer.testing import CliRunner

import triage
from triage.cli import app, discover

runner = CliRunner()


def test_help_and_version():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == triage.__version__


def test_discover_runs_on_real_package():
    # No module ships a cli.py yet; discovery must still succeed on a fresh root.
    discover(root=typer.Typer(), package=triage)


def _make_pkg(tmp_path, name, subcommands):
    """Build a throwaway package whose sub-packages each register one command."""
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("")
    for sub, command in subcommands.items():
        (root / sub).mkdir()
        (root / sub / "__init__.py").write_text("")
        (root / sub / "cli.py").write_text(
            "def register(app):\n"
            f"    @app.command({command!r})\n"
            "    def _cmd():\n"
            f"        print({sub!r})\n"
        )
    return root


@pytest.fixture
def fake_pkg(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    created = []

    def factory(name, subcommands):
        _make_pkg(tmp_path, name, subcommands)
        created.append(name)
        return importlib.import_module(name)

    yield factory
    for name in created:
        for mod in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
            del sys.modules[mod]


def test_member_cli_modules_are_registered(fake_pkg):
    pkg = fake_pkg("pkg_ok", {"alpha": "hello", "beta": "bye"})
    root = typer.Typer()
    root.callback()(lambda: None)
    assert discover(root=root, package=pkg) == ["alpha", "beta"]
    assert runner.invoke(root, ["hello"]).output.strip() == "alpha"


def test_duplicate_command_names_fail_loudly(fake_pkg):
    pkg = fake_pkg("pkg_dup", {"alpha": "same", "beta": "same"})
    with pytest.raises(RuntimeError, match="same"):
        discover(root=typer.Typer(), package=pkg)
