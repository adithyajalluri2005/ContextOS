"""The README must match the real program: tool names, commands, fields and paths."""

import asyncio
import json
import re
from pathlib import Path

import pytest

from contextos.context import Context
from contextos.store import default_db_path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_readme_lists_exactly_the_real_mcp_tools():
    pytest.importorskip("mcp")
    from mcp import Client

    from contextos.mcp_server import build_server

    async def go():
        async with Client(build_server()) as client:
            return {t.name for t in (await client.list_tools()).tools}

    real = asyncio.run(go())
    in_table = set(re.findall(r"^\| `(\w+)` \|", README, flags=re.MULTILINE)) & {
        n for n in re.findall(r"`(\w+)`", README) if n.endswith(("_context", "_contexts"))
    }
    assert in_table == real


def test_readme_lists_every_context_field():
    for field in Context.model_fields:
        if field in ("id", "created_at", "redacted"):
            continue
        assert f"`{field}`" in README, field


def test_readme_names_the_real_commands_and_paths():
    assert 'pip install -e ".[mcp]"' in README
    assert "CONTEXTOS_PATH mcp" in README
    assert "CONTEXTOS_HOME" in README
    assert "~/.contextos/contextos.db" in README
    assert default_db_path().name == "contextos.db"


def test_readme_json_examples_are_valid():
    blocks = re.findall(r"```json\n(.*?)```", README, flags=re.DOTALL)
    assert blocks
    for block in blocks:
        config = json.loads(block)
        assert config["mcpServers"]["contextos"]["args"] == ["mcp"]


def test_readme_explains_serve_with_the_real_options():
    assert "contextos serve --public-host" in README
    assert "--new-secret" in README
    assert "CONTEXTOS_SECRET" in README
    assert "secret.txt" in README
    assert "8765" in README
    from contextos import mcp_server

    assert mcp_server.SECRET_ENV == "CONTEXTOS_SECRET"
    assert mcp_server.SECRET_FILE == "secret.txt"
