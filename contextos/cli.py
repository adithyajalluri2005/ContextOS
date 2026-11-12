"""The `contextos` command line."""

from typing import Annotated

import typer

from contextos import __version__
from contextos.store import Store

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


@app.command("mcp")
def mcp_command() -> None:
    """Run the MCP server over stdio, so AI tools can save and load contexts."""
    try:
        from contextos import mcp_server
    except ImportError as exc:
        if exc.name is None or not exc.name.startswith("mcp"):
            raise
        typer.echo(
            'Error: the MCP server needs an extra package. Install it with: pip install "contextos[mcp]"',
            err=True,
        )
        raise typer.Exit(code=1) from exc
    mcp_server.run()


PREVIEW_CHARS = 80


def _not_found(context_id: str) -> typer.Exit:
    typer.echo(f"Error: no context with id {context_id!r}. Run `contextos list` to see the ids.", err=True)
    return typer.Exit(code=1)


@app.command("list")
def list_command(
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="How many to show.")] = 20,
    source: Annotated[
        str | None, typer.Option("--source", help="Only contexts saved from this tool, e.g. claude-code.")
    ] = None,
) -> None:
    """List saved contexts, newest first."""
    contexts = Store().recent(limit=limit, source_tool=source)
    if not contexts:
        typer.echo("No saved contexts yet.")
        return
    for ctx in contexts:
        tool = f"  [{ctx.source_tool}]" if ctx.source_tool else ""
        typer.echo(f"{ctx.id:>4}  {ctx.created_at:%Y-%m-%d %H:%M}  {ctx.title}{tool}")
        summary = " ".join(ctx.summary.split())
        if len(summary) > PREVIEW_CHARS:
            summary = summary[:PREVIEW_CHARS].rstrip() + "..."
        typer.echo(f"      {summary}")


@app.command("show")
def show_command(
    context_id: Annotated[str, typer.Argument(metavar="ID", help="The id from `contextos list`.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of Markdown.")] = False,
) -> None:
    """Print one saved context."""
    ctx = Store().get(context_id)
    if ctx is None:
        raise _not_found(context_id)
    typer.echo(ctx.model_dump_json(indent=2) if as_json else ctx.to_markdown())


@app.command("delete")
def delete_command(
    context_id: Annotated[str, typer.Argument(metavar="ID", help="The id from `contextos list`.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Delete without asking first.")] = False,
) -> None:
    """Delete one saved context. This cannot be undone."""
    store = Store()
    ctx = store.get(context_id)
    if ctx is None:
        raise _not_found(context_id)
    if not yes and not typer.confirm(f"Delete context {ctx.id} ({ctx.title!r})?", default=False):
        typer.echo("Nothing deleted.")
        raise typer.Exit(code=1)
    store.delete(context_id)
    typer.echo(f"Deleted context {ctx.id}.")
