"""Command-line entry point. Each later command (import, list, pack, ...) is added here."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from contextos import __version__

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
