"""The `contextos` command line."""

from typing import Annotated

import typer

from contextos import __version__

app = typer.Typer(
    help="Save the context of one AI chat and load it in another.",
    no_args_is_help=True,
)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"contextos {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Save the context of one AI chat and load it in another."""
