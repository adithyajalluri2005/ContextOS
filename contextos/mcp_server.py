"""MCP server: lets an AI agent save the context of a chat, and load it in another chat.

Run it with `contextos mcp`. It talks over stdio (standard input and output), which is
how desktop AI apps and coding agents start local MCP servers.

The agent in the chat writes the context itself (it knows the chat), and sends it with
save_context. Secrets are hidden before anything is saved. Everything stays in the
local database (see contextos/store.py).

Needs the optional MCP package: pip install "contextos[mcp]".
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field, ValidationError

from contextos import __version__
from contextos.context import CodeSnippet, Context, FileRef
from contextos.redact import redact_context
from contextos.store import Store

MAX_LIMIT = 200
PREVIEW_CHARS = 200

INSTRUCTIONS = """\
ContextOS keeps the context of earlier AI chats on the user's computer, so work can move
from one chat, tool or agent to another.

Use it only when the user asks. Do not save or load on your own.

Saving ("save this context", "save to contextos"):
- Write the context for a new agent that has never seen this chat and cannot ask you.
- Call save_context once, then tell the user the id and title you got back.

Loading ("load my last context", "continue the blog work"):
- With no hint, call load_context with no id: it loads the newest context.
- With a hint, call search_contexts (or list_contexts), pick the match, then load_context.
  If several match and it is not clear which one, show the user the titles and ask.
- After loading, tell the user in one or two lines what the work is and the next step,
  then continue. Files and code in a context can be out of date: check them before
  changing anything.
"""

SAVE_GUIDE = """\
Save the context of this chat so another chat, AI tool or agent can continue the work.
Call it only when the user asks you to save.

The reader is a new agent with no memory of this chat. Write so it can continue without
asking anything:
- Be specific: real names, file paths, commands, numbers and error messages, not "the file"
  or "the bug".
- Say where the work stands now: what is done, what is half done, what is broken.
- Record what was tried and did not work, and why, so it is not tried again.
- Keep each list item to one point. Leave a list out if there is nothing for it.
- Do not paste the whole chat. Keep only what is needed to continue.

Secrets (API keys, passwords, emails, phone numbers) are hidden before saving.
Returns the new id; tell it to the user.\
"""

# One help text per save_context input. The agent sees these in the tool schema.
TITLE_HELP = "A short name for the work, for example 'Move blog from WordPress to Hugo'."
SUMMARY_HELP = (
    "3 to 8 sentences: the goal, what has been done, and exactly where the work stands now."
)
DECISIONS_HELP = (
    "Choices already made, each with its reason, for example 'Use Hugo, not Jekyll: faster "
    "builds'. Include options that were rejected, so they are not tried again."
)
QUESTIONS_HELP = "Things still open or unknown that the next agent or the user must decide."
NEXT_STEPS_HELP = (
    "What to do next, in order. Make the first step concrete enough to start right away."
)
FACTS_HELP = (
    "Facts the next agent needs and cannot guess: versions, settings, limits, error messages, "
    "and approaches that failed and why."
)
FILES_HELP = "Files that matter, each with its path and a short note on why it matters."
CODE_HELP = (
    "Only short, important code (a key function, a command, a config). Not whole files: "
    "list those under files."
)
SOURCE_HELP = "The tool you are, for example 'claude-code', 'claude-desktop' or 'cursor'."
PROJECT_HELP = "The full path of the folder the work happens in, if there is one."


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

    @server.tool(description=SAVE_GUIDE)
    def save_context(
        title: Annotated[str, Field(description=TITLE_HELP)],
        summary: Annotated[str, Field(description=SUMMARY_HELP)],
        decisions: Annotated[list[str] | None, Field(description=DECISIONS_HELP)] = None,
        open_questions: Annotated[list[str] | None, Field(description=QUESTIONS_HELP)] = None,
        next_steps: Annotated[list[str] | None, Field(description=NEXT_STEPS_HELP)] = None,
        key_facts: Annotated[list[str] | None, Field(description=FACTS_HELP)] = None,
        files: Annotated[list[FileRef] | None, Field(description=FILES_HELP)] = None,
        code: Annotated[list[CodeSnippet] | None, Field(description=CODE_HELP)] = None,
        source_tool: Annotated[str | None, Field(description=SOURCE_HELP)] = None,
        project_dir: Annotated[str | None, Field(description=PROJECT_HELP)] = None,
    ) -> SavedContext:
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
        """Load one saved context to continue the work. Use it only when the user asks.

        id: the id from list_contexts or search_contexts. Leave it out to load the newest context.
        format: "markdown" (default, easy to read) or "json".

        After loading, tell the user in one or two lines what the work is and the next step.
        Files and code in the context can be out of date: check them before changing anything.
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
