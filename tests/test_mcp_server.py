"""The MCP server, tested with the official MCP SDK client. All data here is made up.

Most tests connect in-process (fast). One test starts `contextos mcp` as a separate
program and talks to it over stdio, exactly as an AI app would.
"""

import asyncio
import json
import os
import sys

import pytest

# Locally these tests skip when the optional mcp package is missing. CI sets
# CONTEXTOS_REQUIRE_MCP=1, so there a missing package fails the run instead of
# quietly skipping.
if os.environ.get("CONTEXTOS_REQUIRE_MCP") == "1":
    import mcp  # noqa: F401
else:
    pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from contextos.mcp_server import build_server  # noqa: E402
from contextos.store import Store  # noqa: E402

EMAIL = "riya@example.com"

BLOG = {
    "title": "Move blog to Hugo",
    "summary": "Moving a small WordPress blog to Hugo. Posts are converted; redirects are next.",
    "decisions": ["Use Hugo", "Keep old URLs with redirects"],
    "next_steps": ["Write redirects.txt"],
    "files": [{"path": "config.toml", "note": "site settings"}],
    "code": [{"content": "hugo --minify", "language": "bash"}],
    "source_tool": "claude-code",
    "project_dir": "D:/blog",
}

AUTH = {
    "title": "Fix login token bug",
    "summary": f"Tokens expire too early. Send the report to {EMAIL}.",
    "next_steps": ["Change < to <= in the expiry check"],
    "source_tool": "cursor",
}


def call(tool: str, args: dict | None = None):
    """Call one tool on a fresh in-process server and return the result."""

    async def go():
        async with Client(build_server()) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(go())


def data(result):
    assert not result.is_error, result.content
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


def text(result) -> str:
    return result.content[0].text


def save(args: dict) -> str:
    return data(call("save_context", args))["id"]


# --- the server ----------------------------------------------------------------


def test_server_offers_four_tools_with_descriptions():
    async def go():
        async with Client(build_server()) as client:
            return (await client.list_tools()).tools, client.server_info, client.instructions

    tools, info, instructions = asyncio.run(go())
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"save_context", "list_contexts", "search_contexts", "load_context"}
    assert all(t.description for t in tools)
    assert sorted(by_name["save_context"].input_schema["required"]) == ["summary", "title"]
    assert by_name["search_contexts"].input_schema["required"] == ["query"]
    assert "required" not in by_name["load_context"].input_schema
    assert info.name == "contextos"
    assert "save_context" in instructions and "load_context" in instructions


def tools_and_instructions():
    async def go():
        async with Client(build_server()) as client:
            tools = (await client.list_tools()).tools
            return {t.name: t for t in tools}, client.instructions

    return asyncio.run(go())


def test_instructions_say_use_only_when_the_user_asks():
    tools, instructions = tools_and_instructions()
    assert "only when the user asks" in instructions
    assert "Do not save or load on your own" in instructions
    assert "only when the user asks" in tools["save_context"].description
    assert "only when the user asks" in tools["load_context"].description.lower()


def test_instructions_explain_loading_steps():
    _, instructions = tools_and_instructions()
    assert "load_context with no id" in instructions
    assert "search_contexts" in instructions
    assert "out of date" in instructions


def test_save_guide_is_written_for_a_reader_with_no_memory():
    description = tools_and_instructions()[0]["save_context"].description
    for phrase in ("no memory of this chat", "Be specific", "tried and did not work", "tell it to the user"):
        assert phrase in description


def test_every_save_input_has_its_own_description():
    schema = tools_and_instructions()[0]["save_context"].input_schema
    properties = schema["properties"]
    assert set(properties) == {
        "title", "summary", "decisions", "open_questions", "next_steps",
        "key_facts", "files", "code", "source_tool", "project_dir",
    }
    for name, prop in properties.items():
        assert len(prop.get("description", "")) > 20, name
    assert "rejected" in properties["decisions"]["description"]


# --- save_context --------------------------------------------------------------


def test_save_context_stores_everything():
    result = data(call("save_context", BLOG))
    assert result == {"id": "1", "title": "Move blog to Hugo", "redacted": {}}
    stored = Store().get("1")
    assert stored.decisions == BLOG["decisions"]
    assert stored.files[0].path == "config.toml"
    assert stored.code[0].language == "bash"
    assert stored.source_tool == "claude-code"
    assert stored.redacted == {}


def test_save_context_hides_secrets_before_saving():
    result = data(call("save_context", AUTH))
    assert result["redacted"] == {"email": 1}
    stored = Store().get(result["id"])
    assert EMAIL not in stored.model_dump_json()
    assert "[hidden: email]" in stored.summary


def test_save_context_needs_title_and_summary():
    result = call("save_context", {"title": "   ", "summary": "S"})
    assert result.is_error
    assert "title" in text(result)
    assert Store().recent() == []


def test_save_context_rejects_bad_file_entry():
    result = call("save_context", {"title": "T", "summary": "S", "files": [{"note": "no path"}]})
    assert result.is_error
    assert Store().recent() == []


# --- list_contexts -------------------------------------------------------------


def test_list_contexts_newest_first_with_preview():
    save(BLOG)
    save(AUTH)
    rows = data(call("list_contexts"))
    assert [r["title"] for r in rows] == ["Fix login token bug", "Move blog to Hugo"]
    blog = rows[1]
    assert blog["id"] == "1"
    assert blog["source_tool"] == "claude-code"
    assert blog["project_dir"] == "D:/blog"
    assert blog["preview"] == BLOG["summary"]
    assert len(blog["saved_at"]) == len("2026-11-09 14:30")


def test_list_contexts_filter_and_limit():
    save(BLOG)
    save(AUTH)
    assert [r["title"] for r in data(call("list_contexts", {"source_tool": "cursor"}))] == ["Fix login token bug"]
    assert len(data(call("list_contexts", {"limit": 1}))) == 1
    assert len(data(call("list_contexts", {"limit": 0}))) == 1  # at least 1


def test_list_contexts_long_summary_is_shortened():
    save({"title": "Long", "summary": "word " * 100})
    preview = data(call("list_contexts"))[0]["preview"]
    assert preview.endswith("...")
    assert len(preview) <= 203


def test_list_contexts_empty():
    assert data(call("list_contexts")) == []


# --- search_contexts -----------------------------------------------------------


def test_search_contexts_finds_every_word():
    save(BLOG)
    save(AUTH)
    assert [r["title"] for r in data(call("search_contexts", {"query": "hugo redirects"}))] == ["Move blog to Hugo"]
    assert [r["title"] for r in data(call("search_contexts", {"query": "TOKEN"}))] == ["Fix login token bug"]
    assert data(call("search_contexts", {"query": "hugo token"})) == []


def test_search_contexts_cannot_find_hidden_secrets():
    save(AUTH)
    assert data(call("search_contexts", {"query": EMAIL})) == []


def test_search_contexts_empty_query_is_an_error():
    result = call("search_contexts", {"query": "  "})
    assert result.is_error
    assert "empty" in text(result)


# --- load_context --------------------------------------------------------------


def test_load_context_markdown_by_id():
    save(BLOG)
    save(AUTH)
    result = call("load_context", {"id": "1"})
    assert not result.is_error, result.content
    md = text(result)
    assert md.startswith("# Move blog to Hugo\n")
    assert "- Keep old URLs with redirects" in md
    assert "```bash\nhugo --minify\n```" in md


def test_load_context_without_id_loads_newest():
    save(BLOG)
    save(AUTH)
    md = text(call("load_context"))
    assert md.startswith("# Fix login token bug\n")
    assert "Hidden for safety: 1 email" in md


def test_load_context_json():
    save(BLOG)
    loaded = json.loads(text(call("load_context", {"id": "1", "format": "json"})))
    assert loaded["id"] == "1"
    assert loaded["title"] == "Move blog to Hugo"
    assert loaded["files"] == [{"path": "config.toml", "note": "site settings"}]


def test_load_context_unknown_id():
    result = call("load_context", {"id": "42"})
    assert result.is_error
    assert "No context with id '42'" in text(result)


def test_load_context_when_nothing_is_saved():
    result = call("load_context")
    assert result.is_error
    assert "No context has been saved yet" in text(result)


def test_load_context_rejects_unknown_format():
    save(BLOG)
    assert call("load_context", {"id": "1", "format": "pdf"}).is_error


# --- over stdio: chat A saves, chat B loads -------------------------------------


def test_save_in_one_session_and_load_in_another(tmp_path):
    """Two separate `contextos mcp` programs, like two AI tools, share one local database."""
    env = {"CONTEXTOS_HOME": str(tmp_path / "home")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "contextos", "mcp"], env=env)

    async def chat_a():
        async with Client(params, read_timeout_seconds=60) as client:
            return await client.call_tool("save_context", BLOG)

    async def chat_b():
        async with Client(params, read_timeout_seconds=60) as client:
            found = await client.call_tool("search_contexts", {"query": "hugo"})
            context_id = found.structured_content["result"][0]["id"]
            return await client.call_tool("load_context", {"id": context_id})

    saved = asyncio.run(chat_a())
    assert not saved.is_error, saved.content
    loaded = asyncio.run(chat_b())
    assert not loaded.is_error, loaded.content
    assert loaded.content[0].text.startswith("# Move blog to Hugo\n")
    assert "Write redirects.txt" in loaded.content[0].text
