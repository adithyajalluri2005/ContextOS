"""Command-line entry point. Each later command (import, list, pack, ...) is added here."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from contextos import __version__
from contextos.importers import ImportFailed, ImportResult, ParsedExport, save_all
from contextos.pack import json_schema
from contextos.store import ConversationSummary, Store

app = typer.Typer(
    name="contextos",
    help="Move AI conversations between tools, accounts and teammates.",
    no_args_is_help=True,
    add_completion=False,
)
import_app = typer.Typer(help="Import conversations from an AI tool.", no_args_is_help=True)
app.add_typer(import_app, name="import")

MAX_SKIP_LINES = 5


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"contextos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """Move AI conversations between tools, accounts and teammates."""


@app.command()
def schema(
    out: Annotated[
        Optional[Path],
        typer.Option("--out", "-o", help="File to write. Prints to the screen if left out."),
    ] = None,
) -> None:
    """Write the JSON Schema of the Context Pack format."""
    text = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if out is None:
        typer.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps the file identical on Windows, macOS and Linux.
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    typer.echo(f"Wrote {out}")


# --- import ------------------------------------------------------------------


def _report(tool_name: str, result: ImportResult, store: Store) -> None:
    typer.echo(
        f"Imported {result.total} conversation(s) from {tool_name}: "
        f"{result.created} new, {result.updated} updated, {result.unchanged} unchanged."
    )
    if result.skipped:
        typer.echo(f"Skipped {len(result.skipped)}:")
        for reason in result.skipped[:MAX_SKIP_LINES]:
            typer.echo(f"  - {reason}")
        if len(result.skipped) > MAX_SKIP_LINES:
            typer.echo(f"  ... and {len(result.skipped) - MAX_SKIP_LINES} more")
    typer.echo(f"Saved in {store.path}")


def _run_import(tool_name: str, read: Callable[[], ParsedExport]) -> None:
    try:
        parsed = read()
    except ImportFailed as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    with Store() as store:
        _report(tool_name, save_all(parsed, store), store)


@import_app.command("chatgpt")
def import_chatgpt(
    path: Annotated[
        Path,
        typer.Argument(help="The ChatGPT export ZIP, the unzipped folder, or conversations.json."),
    ],
) -> None:
    """Import an official ChatGPT data export (Settings → Data controls → Export data)."""
    from contextos.importers import chatgpt

    _run_import("ChatGPT", lambda: chatgpt.read_export(path))


@import_app.command("claude-ai")
def import_claude_ai(
    path: Annotated[
        Path,
        typer.Argument(help="The Claude export ZIP, the unzipped folder, or conversations.json."),
    ],
) -> None:
    """Import an official Claude.ai data export (Settings → Privacy → Export data)."""
    from contextos.importers import claude_ai

    _run_import("Claude.ai", lambda: claude_ai.read_export(path))


@import_app.command("claude-code")
def import_claude_code(
    path: Annotated[
        Optional[Path],
        typer.Option(
            "--path",
            "-p",
            help="Projects folder, one project folder, or one .jsonl file. Default: ~/.claude/projects",
        ),
    ] = None,
) -> None:
    """Import Claude Code sessions saved on this computer."""
    from contextos.importers import claude_code

    _run_import("Claude Code", lambda: claude_code.read_sessions(path))


# --- list and show -----------------------------------------------------------

# The source names the importers write into the store.
SOURCES = ("chatgpt", "claude-ai", "claude-code")
TITLE_WIDTH = 60
UNTITLED = "(untitled)"


def _when(conv: ConversationSummary) -> datetime | None:
    """The date shown for a conversation: last change, else start, else import time."""
    return conv.updated_at or conv.created_at or conv.imported_at


def _date(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d") if value else "-"


def _datetime(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if value else "-"


def _shorten(text: str, width: int) -> str:
    text = " ".join(text.split())  # titles can hold new lines or tabs
    return text if len(text) <= width else text[: width - 3] + "..."


@app.command("list")
def list_conversations(
    source: Annotated[
        Optional[str],
        typer.Option("--source", "-s", help=f"Only show one source: {', '.join(SOURCES)}."),
    ] = None,
) -> None:
    """List imported conversations, newest first."""
    if source is not None and source not in SOURCES:
        typer.echo(f"Error: unknown source '{source}'. Choose one of: {', '.join(SOURCES)}.", err=True)
        raise typer.Exit(code=2)

    with Store() as store:
        convs = store.list_conversations(source)

    if not convs:
        if source:
            typer.echo(f"No conversations from {source}.")
        else:
            typer.echo("No conversations yet. Import some first, for example: contextos import chatgpt <export.zip>")
        return

    rows = [
        (str(c.id), c.source_tool, _date(_when(c)), str(c.message_count), _shorten(c.title or UNTITLED, TITLE_WIDTH))
        for c in convs
    ]
    header = ("ID", "SOURCE", "DATE", "MESSAGES", "TITLE")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header) - 1)]
    right_aligned = {0, 3}  # numbers line up on the right

    def line(cells: tuple[str, ...]) -> str:
        parts = [
            cell.rjust(widths[i]) if i in right_aligned else cell.ljust(widths[i])
            for i, cell in enumerate(cells[:-1])
        ]
        return "  ".join([*parts, cells[-1]])

    typer.echo(line(header))
    for row in rows:
        typer.echo(line(row))
    typer.echo(f"\n{len(rows)} conversation(s).")


@app.command("show")
def show_conversation(
    conversation_id: Annotated[int, typer.Argument(metavar="ID", help="The ID from `contextos list`.")],
) -> None:
    """Print one imported conversation."""
    with Store() as store:
        conv = store.get(conversation_id)

    if conv is None:
        typer.echo(f"Error: no conversation with ID {conversation_id}. Run `contextos list` to see the IDs.", err=True)
        raise typer.Exit(code=1)

    typer.echo(conv.title or UNTITLED)
    typer.echo(f"Source:   {conv.source_tool} ({conv.source_id})")
    typer.echo(f"Started:  {_datetime(conv.created_at)}")
    typer.echo(f"Updated:  {_datetime(conv.updated_at)}")
    if conv.url:
        typer.echo(f"Link:     {conv.url}")
    typer.echo(f"Messages: {conv.message_count}")

    for msg in conv.messages:
        stamp = f", {_datetime(msg.created_at)}" if msg.created_at else ""
        typer.echo(f"\n--- {msg.role}{stamp} ---")
        typer.echo(msg.content)


# --- pack --------------------------------------------------------------------


def get_provider():
    """Pick the AI provider from the environment. A separate function so tests can replace it."""
    from contextos.llm import get_provider as from_env

    return from_env()


@app.command("pack")
def pack_conversation(
    conversation_id: Annotated[int, typer.Argument(metavar="ID", help="The ID from `contextos list`.")],
    out: Annotated[
        Optional[Path],
        typer.Option("--out", "-o", help="File to write. Prints to the screen if left out."),
    ] = None,
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="markdown (paste into a chat), json, or claude-md (for CLAUDE.md / AGENTS.md)."),
    ] = "markdown",
    with_transcript: Annotated[
        bool,
        typer.Option("--with-transcript", help="Also include the full conversation. Makes the pack much longer."),
    ] = False,
) -> None:
    """Build a Context Pack from one conversation, so you can continue it in another tool."""
    from contextos.llm import ProviderError
    from contextos.pack import FORMATS, render
    from contextos.pack.builder import PackBuildError, build_pack

    if fmt not in FORMATS:
        typer.echo(f"Error: unknown format '{fmt}'. Choose one of: {', '.join(FORMATS)}.", err=True)
        raise typer.Exit(code=2)

    with Store() as store:
        conv = store.get(conversation_id)
    if conv is None:
        typer.echo(f"Error: no conversation with ID {conversation_id}. Run `contextos list` to see the IDs.", err=True)
        raise typer.Exit(code=1)

    def progress(step: str) -> None:
        typer.echo(step, err=True)

    try:
        provider = get_provider()
        progress(f"Building the pack with {provider.name} ({provider.model}) ...")
        pack = build_pack(conv, provider, include_transcript=with_transcript, progress=progress)
    except (ProviderError, PackBuildError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    text = render(pack, fmt)
    if out is None:
        typer.echo(text, nl=False)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    typer.echo(f"Wrote {out}", err=True)
