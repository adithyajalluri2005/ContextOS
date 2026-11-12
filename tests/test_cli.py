"""Tests for the `contextos` command line."""

import json
import os
import subprocess
import sys

from typer.testing import CliRunner

from contextos import __version__
from contextos.cli import app
from contextos.context import Context
from contextos.store import Store

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


# --- list, show, delete -----------------------------------------------------------


def _save(title="Fix login bug", summary="Made-up test chat about a login bug.", **kw):
    return Store().save(Context(title=title, summary=summary, **kw))


def test_list_when_empty():
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No saved contexts yet." in result.output


def test_list_shows_newest_first_with_preview():
    _save(title="First", summary="older one")
    _save(title="Second", summary="x" * 200, source_tool="claude-code")
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert result.output.index("Second") < result.output.index("First")
    assert "[claude-code]" in result.output
    assert "x" * 80 + "..." in result.output
    assert "x" * 81 not in result.output


def test_list_limit_and_source():
    _save(title="Alpha", source_tool="cursor")
    _save(title="Bravo", source_tool="claude-code")
    _save(title="Charlie", source_tool="claude-code")
    out = runner.invoke(app, ["list", "--limit", "1"]).output
    assert "Charlie" in out and "Bravo" not in out and "Alpha" not in out
    out = runner.invoke(app, ["list", "--source", "cursor"]).output
    assert "Alpha" in out and "Bravo" not in out and "Charlie" not in out


def test_show_markdown_and_json():
    ctx = _save(decisions=["Use SQLite"])
    md = runner.invoke(app, ["show", ctx.id])
    assert md.exit_code == 0
    assert md.output == ctx.to_markdown() + "\n"
    js = runner.invoke(app, ["show", ctx.id, "--json"])
    assert js.exit_code == 0
    assert json.loads(js.output)["decisions"] == ["Use SQLite"]


def test_show_unknown_id():
    result = runner.invoke(app, ["show", "99"])
    assert result.exit_code == 1
    assert "no context with id '99'" in result.output


def test_delete_with_yes():
    ctx = _save()
    result = runner.invoke(app, ["delete", ctx.id, "--yes"])
    assert result.exit_code == 0
    assert f"Deleted context {ctx.id}." in result.output
    assert Store().get(ctx.id) is None


def test_delete_asks_and_can_be_refused():
    ctx = _save()
    result = runner.invoke(app, ["delete", ctx.id], input="n\n")
    assert result.exit_code == 1
    assert "Nothing deleted." in result.output
    assert Store().get(ctx.id) is not None
    result = runner.invoke(app, ["delete", ctx.id], input="y\n")
    assert result.exit_code == 0
    assert Store().get(ctx.id) is None


def test_delete_unknown_id():
    result = runner.invoke(app, ["delete", "abc", "--yes"])
    assert result.exit_code == 1
    assert "no context with id 'abc'" in result.output


def test_list_and_show_print_any_language_when_output_is_redirected():
    """Windows sends piped output as cp1252, which cannot hold Japanese or emoji.

    PYTHONIOENCODING=cp1252 makes every system behave like that, so this test fails
    everywhere if the command line stops writing UTF-8.
    """
    ctx = _save(title="Notes 日本語 ✅ – done", summary="Made-up: emoji 🎉 and Ελληνικά.")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    for args in (["list"], ["show", ctx.id], ["show", ctx.id, "--json"]):
        result = subprocess.run(
            [sys.executable, "-m", "contextos", *args], capture_output=True, env=env, check=False
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        out = result.stdout.decode("utf-8")
        if args[-1] == "--json":
            assert json.loads(out)["title"] == ctx.title
        else:
            assert "Notes 日本語 ✅ – done" in out
