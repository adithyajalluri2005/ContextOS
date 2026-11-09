"""MCP server: lets an AI agent save the context of a chat, and load it in another chat.

Run it with `contextos mcp`. It talks over stdio (standard input and output), which is
how desktop AI apps and coding agents start local MCP servers.

The agent in the chat writes the context itself (it knows the chat), and sends it with
save_context. Secrets are hidden before anything is saved. Everything stays in the
local database (see contextos/store.py).

Needs the optional MCP package: pip install "contextos[mcp]".
"""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from contextos import __version__
from contextos.context import CodeSnippet, Context, FileRef
from contextos.redact import redact_context
from contextos.store import Store

MAX_LIMIT = 200
PREVIEW_CHARS = 200

INSTRUCTIONS = (
    "ContextOS keeps the context of earlier AI chats on the user's computer, so work can "
    "move from one chat or tool to another. When the user asks to save the context, call "
    "save_context with a summary of this chat that another agent can continue from. When the "
    "user asks to load or continue earlier work, use list_contexts or search_contexts to find "
    "it, then load_context."
)


class SavedContext(BaseModel):
    """What save_context returns."""

    id: str
    title: str
    redacted: dict[str, int]  # how many secrets of each kind were hidden


class ContextItem(BaseModel):
    """One line in a list or search result."""

    id: str
    title: str
    saved_at: str  # "YYYY-MM-DD HH:MM" in UTC
    source_tool: str | None
    project_dir: str | None
    preview: str  # the start of the summary


def _item(ctx: Context) -> ContextItem:
    preview = ctx.summary if len(ctx.summary) <= PREVIEW_CHARS else ctx.summary[:PREVIEW_CHARS].rstrip() + "..."
    return ContextItem(
        id=ctx.id or "",
        title=ctx.title,
        saved_at=f"{ctx.created_at:%Y-%m-%d %H:%M}",
        source_tool=ctx.source_tool,
        project_dir=ctx.project_dir,
        preview=preview,
    )


def _limit(value: int) -> int:
    return max(1, min(value, MAX_LIMIT))


def _validation_message(exc: ValidationError) -> str:
    problems = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"]) or "input"
        problems.append(f"{where}: {err['msg']}")
    return "The context was not saved. " + "; ".join(problems)


def build_server() -> MCPServer:
    """Make the server. Every tool opens the store fresh, so CONTEXTOS_HOME is read each time."""
    server = MCPServer(name="contextos", version=__version__, instructions=INSTRUCTIONS)

    @server.tool()
    def save_context(
        title: str,
        summary: str,
        decisions: list[str] | None = None,
        open_questions: list[str] | None = None,
        next_steps: list[str] | None = None,
        key_facts: list[str] | None = None,
        files: list[FileRef] | None = None,
        code: list[CodeSnippet] | None = None,
        source_tool: str | None = None,
        project_dir: str | None = None,
    ) -> SavedContext:
        """Save the context of this chat so another chat or AI tool can continue the work.

        title: a short name for the work.
        summary: what the work is about and where it stands now.
        decisions, open_questions, next_steps, key_facts: short items, one point each.
        files: files that matter, each with a path and an optional note.
        code: important code, each with the content, its language and an optional note.
        source_tool: the tool you are, for example "claude-code" or "cursor".
        project_dir: the folder the work happens in, if any.

        Secrets (API keys, passwords, emails, phone numbers) are hidden before saving.
        Returns the new id.
        """
        try:
            ctx = Context(
                title=title,
                summary=summary,
                decisions=decisions or [],
                open_questions=open_questions or [],
                next_steps=next_steps or [],
                key_facts=key_facts or [],
                files=files or [],
                code=code or [],
                source_tool=source_tool,
                project_dir=project_dir,
            )
        except ValidationError as exc:
            raise ToolError(_validation_message(exc)) from exc
        saved = Store().save(redact_context(ctx))
        return SavedContext(id=saved.id or "", title=saved.title, redacted=saved.redacted or {})

    @server.tool()
    def list_contexts(source_tool: str | None = None, limit: int = 20) -> list[ContextItem]:
        """List saved contexts, newest first.

        source_tool: only show contexts saved from one tool, for example "claude-code".
        limit: how many to return (1 to 200).
        """
        return [_item(c) for c in Store().recent(limit=_limit(limit), source_tool=source_tool)]

    @server.tool()
    def search_contexts(query: str, limit: int = 20) -> list[ContextItem]:
        """Find saved contexts that contain every word of `query` in any field. Newest first.

        Upper or lower case does not matter.
        """
        if not query.split():
            raise ToolError("The search query is empty.")
        return [_item(c) for c in Store().search(query, limit=_limit(limit))]

    @server.tool()
    def load_context(id: str | None = None, format: Literal["markdown", "json"] = "markdown") -> str:
        """Load one saved context to continue the work.

        id: the id from list_contexts or search_contexts. Leave it out to load the newest context.
        format: "markdown" (default, easy to read) or "json".
        """
        store = Store()
        if id is None:
            newest = store.recent(limit=1)
            if not newest:
                raise ToolError("No context has been saved yet.")
            ctx = newest[0]
        else:
            found = store.get(id)
            if found is None:
                raise ToolError(f"No context with id {id!r}. Use list_contexts or search_contexts to find one.")
            ctx = found
        return ctx.model_dump_json(indent=2) if format == "json" else ctx.to_markdown()

    return server


def run() -> None:
    """Serve over stdio until the client closes the connection."""
    build_server().run("stdio")


__all__ = ["build_server", "run"]
