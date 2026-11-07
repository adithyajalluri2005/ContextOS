"""MCP server: lets AI tools read your imported chats and fetch Context Packs themselves.

Run it with `contextos mcp`. It talks over stdio (standard input and output), which is
how desktop AI apps and coding agents start local MCP servers.

It uses the same store and the same pack builder as the command-line tool. Secrets are
always hidden: in packs, in titles and in search snippets.

Needs the optional MCP package: pip install "contextos[mcp]".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from contextos import __version__
from contextos.llm import Provider, ProviderError, get_provider
from contextos.pack import render
from contextos.pack.builder import PackBuildError
from contextos.redact import redact_text
from contextos.service import make_pack
from contextos.store import ConversationSummary, Store

SOURCES = ("chatgpt", "claude-ai", "claude-code")
MAX_LIMIT = 200

INSTRUCTIONS = (
    "ContextOS holds AI conversations the user imported from ChatGPT, Claude.ai and Claude Code. "
    "Use list_conversations or search to find a conversation, then get_context_pack with its id "
    "to get a short summary (decisions, open questions, next steps) to continue the work. "
    "Making a pack calls the user's chosen AI model, so it can take a while."
)


class ConversationItem(BaseModel):
    id: int
    source: str
    title: str | None
    date: str | None  # last change, else start, else import time, as YYYY-MM-DD (UTC)
    message_count: int


class SearchItem(ConversationItem):
    snippet: str | None  # text around the first match; None when only the title matched


def _date(conv: ConversationSummary) -> str | None:
    when: datetime | None = conv.updated_at or conv.created_at or conv.imported_at
    return when.astimezone(timezone.utc).strftime("%Y-%m-%d") if when else None


def _clean(text: str | None) -> str | None:
    return redact_text(text, Counter()) if text else text


def _item(conv: ConversationSummary) -> dict:
    return {
        "id": conv.id,
        "source": conv.source_tool,
        "title": _clean(conv.title),
        "date": _date(conv),
        "message_count": conv.message_count,
    }


def _limit(value: int) -> int:
    return max(1, min(value, MAX_LIMIT))


def build_server(provider_factory: Callable[[], Provider] = get_provider) -> MCPServer:
    """Make the server. Tests pass their own `provider_factory`; normally the provider comes from
    CONTEXTOS_PROVIDER, the same as for `contextos pack`."""
    server = MCPServer(name="contextos", version=__version__, instructions=INSTRUCTIONS)

    @server.tool()
    def list_conversations(source: str | None = None, limit: int = 50) -> list[ConversationItem]:
        """List imported conversations, newest first.

        source: only show one tool: "chatgpt", "claude-ai" or "claude-code".
        limit: how many to return (1 to 200).
        """
        if source is not None and source not in SOURCES:
            raise ToolError(f"Unknown source '{source}'. Choose one of: {', '.join(SOURCES)}.")
        with Store() as store:
            convs = store.list_conversations(source)[: _limit(limit)]
        return [ConversationItem(**_item(c)) for c in convs]

    @server.tool()
    def search(query: str, limit: int = 20) -> list[SearchItem]:
        """Find conversations that contain every word of `query`, in the title or the messages.

        Returns newest first, each with a short piece of matching text.
        """
        if not query.split():
            raise ToolError("The search query is empty.")
        with Store() as store:
            hits = store.search(query, limit=_limit(limit))
        return [SearchItem(**_item(h), snippet=_clean(h.snippet)) for h in hits]

    @server.tool()
    def get_context_pack(id: int, format: Literal["markdown", "json", "claude-md"] = "markdown") -> str:
        """Build a Context Pack for one conversation: a short summary with decisions, open questions,
        next steps, key facts and code, ready to continue the work.

        id: the conversation id from list_conversations or search.
        format: "markdown" (default), "json", or "claude-md" (a section for CLAUDE.md or AGENTS.md).
        """
        with Store() as store:
            conv = store.get(id)
        if conv is None:
            raise ToolError(f"No conversation with id {id}. Use list_conversations or search to find one.")
        try:
            pack = make_pack(conv, provider_factory())
        except (ProviderError, PackBuildError) as exc:
            raise ToolError(str(exc)) from exc
        return render(pack, format)

    return server


def run() -> None:
    """Serve over stdio until the client closes the connection."""
    build_server().run("stdio")


__all__ = ["build_server", "run"]
