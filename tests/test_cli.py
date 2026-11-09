"""Tests for the `contextos` command line skeleton."""

import subprocess
import sys

from typer.testing import CliRunner

from contextos import __version__
from contextos.cli import app

runner = CliRunner()


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"contextos {__version__}"


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_python_dash_m_works():
    result = subprocess.run(
        [sys.executable, "-m", "contextos", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_mcp_command_explains_missing_package(monkeypatch):
    """Without the mcp package, `contextos mcp` says how to install it instead of crashing."""
    import builtins

    import contextos

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError(f"No module named '{name}'", name="mcp")
        return real_import(name, *args, **kwargs)

    # Forget an already loaded server, so the command has to import it again.
    monkeypatch.delitem(sys.modules, "contextos.mcp_server", raising=False)
    monkeypatch.delattr(contextos, "mcp_server", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 1
    assert 'pip install "contextos[mcp]"' in result.output
