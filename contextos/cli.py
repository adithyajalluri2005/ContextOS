"""Command-line entry point. Each later command (import, list, pack, ...) is added here."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Optional

import typer

from contextos import __version__
from contextos.importers import ImportFailed, ImportResult, ParsedExport, save_all
from contextos.pack import json_schema
from contextos.store import Store

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
