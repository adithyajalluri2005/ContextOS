"""The Context Pack format: a short, portable summary of an AI conversation.

A pack is what moves between tools. It is small enough to paste into a new chat,
structured enough for a program to read, and never tied to one AI vendor.
See SPEC.md for the human description of every field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SPEC_VERSION = "0.1"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "context-pack.schema.json"

Role = Literal["user", "assistant", "system", "tool"]


class _PackModel(BaseModel):
    """Shared settings: trim text, and reject unknown fields so typos are caught early."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(_PackModel):
    """Where the conversation came from."""

    tool: str = Field(
        min_length=1,
        description='Tool the conversation was taken from, e.g. "chatgpt", "claude-ai", "claude-code".',
    )
    conversation_id: str | None = Field(default=None, description="ID of the conversation in the original tool.")
    title: str | None = Field(default=None, description="Title of the original conversation.")
    url: str | None = Field(default=None, description="Link to the original conversation, if there is one.")
    created_at: AwareDatetime | None = Field(default=None, description="When the conversation started.")
    updated_at: AwareDatetime | None = Field(default=None, description="When the conversation last changed.")


class Decision(_PackModel):
    """Something that was decided, and why."""

    decision: str = Field(min_length=1, description="What was decided.")
    reason: str | None = Field(default=None, description="Why it was decided.")


class CodeSnippet(_PackModel):
    """A piece of code worth carrying over."""

    code: str = Field(min_length=1)
    language: str | None = Field(default=None, description='Language name, e.g. "python".')
    path: str | None = Field(default=None, description="File the code belongs to, if known.")
    description: str | None = Field(default=None, description="What the code does or why it matters.")


class FileRef(_PackModel):
    """A file that the conversation talked about."""

    path: str = Field(min_length=1)
    description: str | None = Field(default=None, description="Why the file matters.")


class Message(_PackModel):
    """One message of the original conversation, used only in raw_transcript."""

    role: Role
    content: str
    created_at: AwareDatetime | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContextPack(_PackModel):
    """A portable summary of one AI conversation."""

    spec_version: Literal["0.1"] = Field(default=SPEC_VERSION, description="Version of this format.")
    title: str = Field(min_length=1, description="Short name for what the conversation is about.")
    summary: str = Field(min_length=1, description="A few sentences a new reader needs first.")
    decisions: list[Decision] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list, description="Questions not yet answered.")
    next_steps: list[str] = Field(default_factory=list, description="Concrete things to do next.")
    key_facts: list[str] = Field(
        default_factory=list, description="Facts to keep: names, versions, limits, numbers."
    )
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    file_refs: list[FileRef] = Field(default_factory=list)
    source: Source
    created_at: AwareDatetime = Field(default_factory=_utc_now, description="When this pack was made.")
    raw_transcript: list[Message] | None = Field(
        default=None, description="Optional full conversation. Leave out to keep the pack small."
    )

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the pack, leaving out empty optional values."""
        return self.model_dump_json(indent=indent, exclude_none=True)

    @classmethod
    def from_json(cls, data: str | bytes) -> ContextPack:
        return cls.model_validate_json(data)


def json_schema() -> dict[str, Any]:
    """JSON Schema for ContextPack, with the standard header fields first."""
    schema = ContextPack.model_json_schema()
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **schema}
