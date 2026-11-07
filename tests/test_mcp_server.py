"""The MCP server, tested with the official MCP SDK client.

Most tests connect in-process (fast). One test starts `contextos mcp` as a separate
program and talks to it over stdio, exactly as an AI app would.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

# Locally these tests skip when the optional mcp package is missing. CI sets
# CONTEXTOS_REQUIRE_MCP=1, so there a missing package fails the run instead of
# quietly skipping, and a green CI run means these tests really ran.
if os.environ.get("CONTEXTOS_REQUIRE_MCP") == "1":
    import mcp  # noqa: F401
else:
    pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from contextos.llm import FakeProvider  # noqa: E402
from contextos.mcp_server import build_server  # noqa: E402
from contextos.pack import ContextPack, Message  # noqa: E402
from contextos.store import ConversationIn, Store  # noqa: E402
from fixtures.make_fixtures import CHATGPT_ZIP  # noqa: E402

EMAIL = "riya@example.com"
DRAFT = {
    "title": "Speed up a slow SQL query",
    "summary": "An index on orders.customer_id fixed the slow report.",
    "decisions": [{"decision": "Add an index", "reason": "The join scanned every row"}],
    "open_questions": [],
    "next_steps": ["Check the live database"],
    "key_facts": [],
    "code_snippets": [],
    "file_refs": [],
}


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def ids():
    convs = {
        "sql": ConversationIn(
            source_tool="claude-ai",
            source_id="cl-1",
            title="Speed up a slow SQL query",
            created_at=at(5),
            messages=[
                Message(role="user", content=f"My join is slow. Mail me at {EMAIL} when done."),
                Message(role="assistant", content="Add an index on orders.customer_id."),
            ],
        ),
        "trip": ConversationIn(
            source_tool="chatgpt",
            source_id="gpt-1",
            title="Plan a weekend in Pune",
            created_at=at(2),
            messages=[Message(role="user", content="Plan two days in Pune with an index of cafes.")],
        ),
        "leaky_title": ConversationIn(
            source_tool="claude-code",
            source_id="cc-1",
            title=f"Email {EMAIL} about invoices",
            created_at=at(1),
            messages=[Message(role="user", content="Draft the invoice email.")],
        ),
    }
    with Store() as store:
        return {name: store.save(c)[0] for name, c in convs.items()}


def call(tool: str, args: dict | None = None, *, provider=None):
    """Call one tool on a fresh in-process server and return the result."""
    fake = provider or FakeProvider(lambda system, prompt: DRAFT)
    server = build_server(lambda: fake)

    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args or {})

    return asyncio.run(go())


def items(result) -> list[dict]:
    assert not result.is_error, result.content
    return result.structured_content["result"]


def text(result) -> str:
    return result.content[0].text


# --- tool list ---------------------------------------------------------------


def test_server_offers_three_tools_with_descriptions():
    async def go():
        async with Client(build_server()) as client:
            return (await client.list_tools()).tools, client.server_info, client.instructions

    tools, info, instructions = asyncio.run(go())
    by_name = {t.name: t for t in tools}
    assert set(by_name) == {"list_conversations", "search", "get_context_pack"}
    assert all(t.description for t in tools)
    assert by_name["get_context_pack"].input_schema["required"] == ["id"]
    assert by_name["search"].input_schema["required"] == ["query"]
    assert info.name == "contextos"
    assert "get_context_pack" in instructions


# --- list_conversations ------------------------------------------------------


def test_list_conversations_newest_first(ids):
    rows = items(call("list_conversations"))
    assert [r["id"] for r in rows] == [ids["sql"], ids["trip"], ids["leaky_title"]]
    assert rows[0] == {
        "id": ids["sql"],
        "source": "claude-ai",
        "title": "Speed up a slow SQL query",
        "date": "2026-03-05",
        "message_count": 2,
    }


def test_list_conversations_filter_and_limit(ids):
    assert [r["id"] for r in items(call("list_conversations", {"source": "chatgpt"}))] == [ids["trip"]]
    assert len(items(call("list_conversations", {"limit": 1}))) == 1


def test_list_conversations_rejects_unknown_source(ids):
    result = call("list_conversations", {"source": "gemini"})
    assert result.is_error
    assert "Unknown source 'gemini'" in text(result)


def test_list_hides_secrets_in_titles(ids):
    titles = [r["title"] for r in items(call("list_conversations"))]
    assert "Email [hidden: email] about invoices" in titles
    assert all(EMAIL not in (t or "") for t in titles)


def test_list_on_empty_store():
    assert items(call("list_conversations")) == []


# --- search ------------------------------------------------------------------


def test_search_finds_words_in_messages_and_titles(ids):
    hits = items(call("search", {"query": "index"}))
    assert [h["id"] for h in hits] == [ids["sql"], ids["trip"]]
    assert hits[0]["snippet"] == "Add an index on orders.customer_id."

    # Every word must appear; the case of letters does not matter.
    assert [h["id"] for h in items(call("search", {"query": "PUNE cafes"}))] == [ids["trip"]]
    assert items(call("search", {"query": "pune orders"})) == []


def test_search_title_only_match_has_no_snippet(ids):
    hits = items(call("search", {"query": "weekend"}))
    assert hits == [
        {"id": ids["trip"], "source": "chatgpt", "title": "Plan a weekend in Pune", "date": "2026-03-02",
         "message_count": 1, "snippet": None}
    ]


def test_search_snippet_hides_secrets(ids):
    hits = items(call("search", {"query": "slow"}))
    assert hits[0]["snippet"] == "My join is slow. Mail me at [hidden: email] when done."


def test_search_treats_like_wildcards_as_plain_text(ids):
    assert items(call("search", {"query": "%"})) == []
    # As a wildcard "_" would match the space in "join is"; as plain text it must not.
    assert items(call("search", {"query": "join_is"})) == []
    # "customer_id" still matches itself.
    assert [h["id"] for h in items(call("search", {"query": "customer_id"}))] == [ids["sql"]]


def test_search_empty_query_is_an_error(ids):
    result = call("search", {"query": "   "})
    assert result.is_error
    assert "empty" in text(result)


# --- get_context_pack --------------------------------------------------------


def test_get_context_pack_markdown_uses_the_pack_builder(ids):
    fake = FakeProvider(lambda system, prompt: DRAFT)
    result = call("get_context_pack", {"id": ids["sql"]}, provider=fake)
    assert not result.is_error, result.content
    md = text(result)
    assert md.startswith("# Context: Speed up a slow SQL query\n")
    assert "- Add an index (reason: The join scanned every row)" in md
    assert "_1 item was hidden for privacy (email: 1)._" in md
    # The model saw the chat, but not the email address.
    assert len(fake.calls) == 1
    assert "My join is slow." in fake.calls[0].prompt
    assert EMAIL not in fake.calls[0].prompt


def test_get_context_pack_json_and_claude_md(ids):
    pack = ContextPack.from_json(text(call("get_context_pack", {"id": ids["sql"], "format": "json"})))
    assert pack.source.conversation_id == "cl-1"
    assert pack.redacted == {"email": 1}
    section = text(call("get_context_pack", {"id": ids["sql"], "format": "claude-md"}))
    assert section.startswith("<!-- contextos:start -->")


def test_get_context_pack_unknown_id(ids):
    result = call("get_context_pack", {"id": 9999})
    assert result.is_error
    assert "No conversation with id 9999" in text(result)


def test_get_context_pack_rejects_unknown_format(ids):
    result = call("get_context_pack", {"id": ids["sql"], "format": "html"})
    assert result.is_error


def test_get_context_pack_reports_provider_errors(ids, monkeypatch):
    monkeypatch.delenv("CONTEXTOS_PROVIDER", raising=False)

    async def go():
        async with Client(build_server()) as client:  # provider from the environment, which is unset
            return await client.call_tool("get_context_pack", {"id": ids["sql"]})

    result = asyncio.run(go())
    assert result.is_error
    assert "CONTEXTOS_PROVIDER" in text(result)


def test_get_context_pack_bad_model_answer_is_an_error(ids):
    result = call("get_context_pack", {"id": ids["sql"]}, provider=FakeProvider(lambda s, p: "not json"))
    assert result.is_error
    assert "usable answer" in text(result)


# --- over stdio, as a separate program -----------------------------------------


def test_contextos_mcp_over_stdio(tmp_path):
    """Start `contextos mcp` the way an AI app does, and use all three tools."""
    env = {"CONTEXTOS_HOME": str(tmp_path / "home"), "CONTEXTOS_PROVIDER": "fake"}
    done = subprocess.run(
        [sys.executable, "-m", "contextos", "import", "chatgpt", str(CHATGPT_ZIP)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr

    params = StdioServerParameters(command=sys.executable, args=["-m", "contextos", "mcp"], env=env)

    async def go():
        async with Client(params, read_timeout_seconds=60) as client:
            listed = await client.call_tool("list_conversations", {})
            found = await client.call_tool("search", {"query": "Dudhsagar"})
            conv_id = found.structured_content["result"][0]["id"]
            pack = await client.call_tool("get_context_pack", {"id": conv_id, "format": "json"})
            return listed, found, pack

    listed, found, pack = asyncio.run(go())
    titles = [r["title"] for r in listed.structured_content["result"]]
    assert "Plan a trip to Goa" in titles and "CSV cleanup in Python" in titles
    assert found.structured_content["result"][0]["title"] == "Plan a trip to Goa"
    assert not pack.is_error, pack.content
    data = json.loads(pack.content[0].text)
    assert data["source"]["title"] == "Plan a trip to Goa"
    assert data["source"]["tool"] == "chatgpt"
