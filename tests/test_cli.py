import subprocess
import sys

from typer.testing import CliRunner

from contextos import __version__
from contextos.cli import app

runner = CliRunner()


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"contextos {__version__}"


def test_short_version_flag():
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_program_purpose():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Move AI conversations" in result.stdout


def test_python_dash_m_entry_point():
    completed = subprocess.run(
        [sys.executable, "-m", "contextos", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert __version__ in completed.stdout
