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
