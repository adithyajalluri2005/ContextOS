"""Command-line entry point. Each later command (import, list, pack, ...) is added here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from contextos import __version__
from contextos.pack import json_schema

app = typer.Typer(
    name="contextos",
    help="Move AI conversations between tools, accounts and teammates.",
    no_args_is_help=True,
    add_completion=False,
)


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
