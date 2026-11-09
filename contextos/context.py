"""The context format: what one saved context holds, and how it is shown as Markdown.

An agent in chat A fills a `Context` and saves it. An agent in chat B loads it and
reads `to_markdown()` to continue the work.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

TITLE_MAX = 200


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_list(items: list[str]) -> list[str]:
    """Strip spaces and drop empty items, so the Markdown has no blank bullets."""
    return [item.strip() for item in items if item and item.strip()]


class FileRef(BaseModel):
    """A file that matters for the work."""

    model_config = ConfigDict(extra="forbid")

    path: Annotated[str, Field(min_length=1)]
    note: str = ""


class CodeSnippet(BaseModel):
    """A piece of code worth keeping, such as a key function or a command."""

    model_config = ConfigDict(extra="forbid")

    content: Annotated[str, Field(min_length=1)]
    language: str = ""
    note: str = ""


class Context(BaseModel):
    """One saved context."""

    model_config = ConfigDict(extra="forbid")

    # Set by the store when the context is saved; empty before that.
    id: str | None = None

    title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
    summary: Annotated[str, Field(min_length=1)]
    decisions: list[str] = []
    open_questions: list[str] = []
    next_steps: list[str] = []
    key_facts: list[str] = []
    files: list[FileRef] = []
    code: list[CodeSnippet] = []

    # Where the context came from, for example "claude-code" or "cursor".
    source_tool: str | None = None
    # The folder the work happened in, if there was one.
    project_dir: str | None = None
    created_at: datetime = Field(default_factory=_now)

    # How many secrets of each kind were hidden, for example {"email": 2}.
    # {} = checked, nothing found. None = not checked.
    redacted: dict[str, int] | None = None

    @field_validator("title", "summary", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("decisions", "open_questions", "next_steps", "key_facts")
    @classmethod
    def _strip_items(cls, value: list[str]) -> list[str]:
        return _clean_list(value)

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        # A time without a zone is taken as UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def to_markdown(self) -> str:
        """Show the context as Markdown for the next agent. Empty sections are left out."""
        lines: list[str] = [f"# {self.title}", ""]

        origin = [f"Saved {self.created_at:%Y-%m-%d %H:%M} UTC"]
        if self.source_tool:
            origin.append(f"from {self.source_tool}")
        if self.project_dir:
            origin.append(f"in `{self.project_dir}`")
        lines += [
            f"> {' '.join(origin)}. This is the context of earlier work. Continue from here.",
        ]
        if self.redacted:
            hidden = ", ".join(f"{count} {kind}" for kind, count in self.redacted.items())
            lines += [
                ">",
                f"> Hidden for safety: {hidden}. Markers like `[hidden: email]` show where."
                " Ask the user if you need the real value.",
            ]
        lines += [
            "",
            "## Summary",
            "",
            self.summary,
            "",
        ]

        for heading, items in (
            ("Decisions", self.decisions),
            ("Open questions", self.open_questions),
            ("Next steps", self.next_steps),
            ("Key facts", self.key_facts),
        ):
            if items:
                lines += [f"## {heading}", "", *(f"- {item}" for item in items), ""]

        if self.files:
            lines += ["## Files", ""]
            for ref in self.files:
                note = f": {ref.note}" if ref.note else ""
                lines.append(f"- `{ref.path}`{note}")
            lines.append("")

        if self.code:
            lines += ["## Code", ""]
            for snippet in self.code:
                if snippet.note:
                    lines += [snippet.note, ""]
                # Use a longer fence if the code itself has ``` in it.
                fence = "````" if "```" in snippet.content else "```"
                lines += [f"{fence}{snippet.language}", snippet.content.rstrip("\n"), fence, ""]

        return "\n".join(lines).rstrip("\n") + "\n"
